"""Sprint A.1 — SignalMar rebranding, pseudo system, v2 report types + TTLs."""
import re
import time
import requests
import pytest
from datetime import datetime, timezone, timedelta


MAINTAINER = {"email": "antoninlepinay@gmail.com", "password": "123454321"}


def _parse_iso(s):
    # Accept both with and without trailing Z / offset.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        # naive fallback
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def fresh_user_token(base_url):
    """Register a brand-new fresh user for the pseudo flow tests."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    email = f"TEST_a1_{int(time.time()*1000)}@example.com"
    r = s.post(f"{base_url}/api/auth/register", json={
        "email": email, "password": "pwd12345", "name": "Test A1",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    return {"token": data["token"], "user": data["user"], "email": email}


@pytest.fixture(scope="module")
def maintainer_token(base_url):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{base_url}/api/auth/login", json=MAINTAINER)
    assert r.status_code == 200, f"maintainer login failed: {r.status_code} {r.text}"
    return r.json()["token"]


# ------------- R1: Rebranding sanity ----------------------------------------
class TestR1Rebranding:
    def test_root_internal_identifier(self, base_url, api_client):
        r = api_client.get(f"{base_url}/api/")
        assert r.status_code == 200
        j = r.json()
        # Internal identifier is allowed to remain "SignMar API"
        assert "name" in j and j.get("ok") is True


# ------------- R2: Pseudo end-to-end ----------------------------------------
class TestR2Pseudo:
    def test_register_sets_nautical_pseudo(self, fresh_user_token):
        u = fresh_user_token["user"]
        assert u.get("pseudo"), "pseudo should be set on register"
        assert re.match(
            r"^(Marin|Capitaine|Skipper|Navigateur|Mousse|Matelot|Quartier-maitre|Pilote|Bosco|Timonier|Vigie|Veilleur)_\d{4}$",
            u["pseudo"],
        ), f"pseudo {u['pseudo']!r} does not match nautical pattern"
        # API contract: name aliased to pseudo
        assert u.get("name") == u["pseudo"]

    def test_me_returns_same_pseudo(self, base_url, fresh_user_token):
        r = requests.get(
            f"{base_url}/api/auth/me",
            headers={"Authorization": f"Bearer {fresh_user_token['token']}"},
        )
        assert r.status_code == 200
        assert r.json()["pseudo"] == fresh_user_token["user"]["pseudo"]

    def test_patch_pseudo_persists(self, base_url, fresh_user_token):
        new_pseudo = f"Capitaine{int(time.time()) % 100000}"
        # Save for later uniqueness check
        fresh_user_token["new_pseudo"] = new_pseudo
        r = requests.patch(
            f"{base_url}/api/auth/me",
            json={"pseudo": new_pseudo},
            headers={"Authorization": f"Bearer {fresh_user_token['token']}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["pseudo"] == new_pseudo
        # GET confirms persistence
        r2 = requests.get(
            f"{base_url}/api/auth/me",
            headers={"Authorization": f"Bearer {fresh_user_token['token']}"},
        )
        assert r2.json()["pseudo"] == new_pseudo

    def test_reserved_pseudo_rejected_for_non_dev(self, base_url, fresh_user_token):
        r = requests.patch(
            f"{base_url}/api/auth/me",
            json={"pseudo": "SignalMar"},
            headers={"Authorization": f"Bearer {fresh_user_token['token']}"},
        )
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
        assert "réservé" in r.json().get("detail", "").lower() or "reserve" in r.json().get("detail", "").lower()

    def test_duplicate_pseudo_rejected(self, base_url, api_client, fresh_user_token):
        # Register a 2nd user
        email2 = f"TEST_a1_dup_{int(time.time()*1000)}@example.com"
        r = api_client.post(f"{base_url}/api/auth/register", json={
            "email": email2, "password": "pwd12345", "name": "Dup User",
        })
        assert r.status_code == 200
        token2 = r.json()["token"]
        # Attempt to grab the same pseudo
        target = fresh_user_token.get("new_pseudo")
        assert target, "first user must have set a pseudo earlier"
        r2 = requests.patch(
            f"{base_url}/api/auth/me",
            json={"pseudo": target},
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert r2.status_code == 409, f"expected 409, got {r2.status_code}: {r2.text}"
        assert "pris" in r2.json().get("detail", "").lower()


# ------------- R3: Maintainer account ---------------------------------------
class TestR3Maintainer:
    def test_login_maintainer(self, base_url):
        r = requests.post(f"{base_url}/api/auth/login", json=MAINTAINER)
        assert r.status_code == 200, r.text
        u = r.json()["user"]
        assert u["pseudo"] == "SignalMar"
        assert u["title"] == "Amiral Modérateur"
        assert u["is_dev"] is True
        assert u["name"] == "SignalMar"  # legacy alias

    def test_me_maintainer(self, base_url, maintainer_token):
        r = requests.get(
            f"{base_url}/api/auth/me",
            headers={"Authorization": f"Bearer {maintainer_token}"},
        )
        assert r.status_code == 200
        u = r.json()
        assert u["pseudo"] == "SignalMar"
        assert u["title"] == "Amiral Modérateur"
        assert u["is_dev"] is True


# ------------- R4 + R6 + R5: New types, TTLs, identity, wipe ----------------
class TestR4ReportsV2:
    created_ids: list = []

    def _create(self, base_url, token, payload):
        return requests.post(
            f"{base_url}/api/reports", json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_animal_marin_mammifere_6h(self, base_url, maintainer_token):
        payload = {
            "type": "animal_marin", "subtype": "mammifere",
            "lat": 47.45, "lng": -3.05,
            "description": "Dauphin commun observé",
            "extras": {"species": "common_dolphin", "health": "alive_healthy"},
        }
        r = self._create(base_url, maintainer_token, payload)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["type"] == "animal_marin"
        assert j["subtype"] == "mammifere"
        assert j["extras"]["species"] == "common_dolphin"
        assert j["extras"]["health"] == "alive_healthy"
        # expires_at ≈ created_at + 6h
        created = _parse_iso(j["created_at"])
        exp = _parse_iso(j["expires_at"])
        diff_min = (exp - created).total_seconds() / 60.0
        assert 358 <= diff_min <= 362, f"expected ~360 min, got {diff_min:.1f}"
        TestR4ReportsV2.created_ids.append(j["id"])

    def test_pollution_cote_24h(self, base_url, maintainer_token):
        payload = {
            "type": "pollution", "subtype": "pollution_cote",
            "lat": 47.42, "lng": -2.95,
            "description": "Nappe d'hydrocarbure",
        }
        r = self._create(base_url, maintainer_token, payload)
        assert r.status_code == 200, r.text
        j = r.json()
        created = _parse_iso(j["created_at"])
        exp = _parse_iso(j["expires_at"])
        diff_min = (exp - created).total_seconds() / 60.0
        assert 1438 <= diff_min <= 1442, f"expected ~1440 min, got {diff_min:.1f}"
        TestR4ReportsV2.created_ids.append(j["id"])

    def test_obstacle_conteneur_1h(self, base_url, maintainer_token):
        payload = {
            "type": "obstacle_nav", "subtype": "conteneur",
            "lat": 47.40, "lng": -3.20,
            "description": "Conteneur partiellement immergé",
        }
        r = self._create(base_url, maintainer_token, payload)
        assert r.status_code == 200, r.text
        j = r.json()
        created = _parse_iso(j["created_at"])
        exp = _parse_iso(j["expires_at"])
        diff_min = (exp - created).total_seconds() / 60.0
        assert 58 <= diff_min <= 62, f"expected ~60 min, got {diff_min:.1f}"
        TestR4ReportsV2.created_ids.append(j["id"])

    def test_autre_free(self, base_url, maintainer_token):
        payload = {
            "type": "autre", "subtype": "autre_libre",
            "lat": 47.50, "lng": -3.00,
            "description": "Phénomène lumineux étrange",
        }
        r = self._create(base_url, maintainer_token, payload)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["type"] == "autre"
        assert j["subtype"] == "autre_libre"
        TestR4ReportsV2.created_ids.append(j["id"])

    def test_legacy_type_rejected(self, base_url, maintainer_token):
        payload = {
            "type": "authorities", "subtype": None,
            "lat": 47.45, "lng": -3.05, "description": "legacy",
        }
        r = self._create(base_url, maintainer_token, payload)
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"

    def test_author_identity_is_pseudo_only(self, base_url, maintainer_token):
        # Re-fetch one of the just-created reports.
        assert TestR4ReportsV2.created_ids, "previous tests must have created reports"
        rid = TestR4ReportsV2.created_ids[0]
        r = requests.get(
            f"{base_url}/api/reports/{rid}",
            headers={"Authorization": f"Bearer {maintainer_token}"},
        )
        assert r.status_code == 200
        j = r.json()
        assert j["author"]["pseudo"] == "SignalMar"
        assert j["author"]["name"] == "SignalMar"  # alias must not leak legal name
        assert "Antonin" not in j["author"].get("name", "")
        assert "Antonin" not in j["author"].get("pseudo", "")

    def test_list_reports_after_wipe(self, base_url, maintainer_token):
        r = requests.get(
            f"{base_url}/api/reports",
            headers={"Authorization": f"Bearer {maintainer_token}"},
        )
        assert r.status_code == 200
        payload = r.json()
        ids = {x["id"] for x in payload}
        # All created in this run must be present.
        for rid in TestR4ReportsV2.created_ids:
            assert rid in ids, f"newly created {rid} missing from list"
        # Anything else must be a demo seed (Phase A.2) OR a live v2 report
        # (carries expires_at — created by users/tests since the wipe). Only
        # stale LEGACY docs (no expires_at, non-demo) are forbidden.
        extras = [x for x in payload if x["id"] not in TestR4ReportsV2.created_ids]
        non_demo_extras = [
            x["id"] for x in extras
            if not x.get("is_demo") and not x.get("expires_at")
        ]
        assert not non_demo_extras, (
            f"unexpected non-demo legacy reports still present: {non_demo_extras}"
        )
