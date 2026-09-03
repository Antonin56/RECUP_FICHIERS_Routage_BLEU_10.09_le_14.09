"""
Iter90 — Backend re-verification for Mode test BETA (routers/beta.py + dev_switch + reports geofence).
Focus: fast pass to reconfirm what main agent has already curl-tested OK.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://moteur-i-routing.preview.emergentagent.com").rstrip("/")
QA_BYPASS = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}

PHONES = {
    "admin": "0760071445",
    "beta1": "0688776655",
    "beta2": "0688776656",
    "nontester": "0699887766",
}


def _login(phone: str) -> str:
    s = requests.Session()
    s.headers.update(QA_BYPASS)
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, f"otp/request {phone}: {r.status_code} {r.text}"
    r = s.post(f"{BASE_URL}/api/auth/otp/verify", json={"phone": phone, "code": "123456"})
    assert r.status_code == 200, f"otp/verify {phone}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def tokens():
    return {k: _login(v) for k, v in PHONES.items()}


def _auth(token):
    return {"Authorization": f"Bearer {token}", **QA_BYPASS}


# ---- beta/status ----

class TestBetaStatus:
    def test_admin_status(self, tokens):
        r = requests.get(f"{BASE_URL}/api/beta/status", headers=_auth(tokens["admin"]))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("is_admin") is True
        # admin has full powers regardless of tester list
        assert "test_mode" in d

    def test_beta1_status(self, tokens):
        r = requests.get(f"{BASE_URL}/api/beta/status", headers=_auth(tokens["beta1"]))
        assert r.status_code == 200
        d = r.json()
        assert d.get("is_tester") is True
        assert d.get("is_admin") is False

    def test_nontester_status(self, tokens):
        r = requests.get(f"{BASE_URL}/api/beta/status", headers=_auth(tokens["nontester"]))
        assert r.status_code == 200
        d = r.json()
        assert d.get("is_tester") is False
        assert d.get("is_admin") is False


# ---- beta/test-mode (403 for non-testers) ----

class TestBetaTestModeAuth:
    def test_nontester_cannot_toggle(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/beta/test-mode",
            headers=_auth(tokens["nontester"]),
            json={"enabled": True},
        )
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

    def test_beta1_can_enable(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/beta/test-mode",
            headers=_auth(tokens["beta1"]),
            json={"enabled": True},
        )
        assert r.status_code == 200, r.text
        assert r.json().get("test_mode") is True

    def test_beta2_can_enable(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/beta/test-mode",
            headers=_auth(tokens["beta2"]),
            json={"enabled": True},
        )
        assert r.status_code == 200
        assert r.json().get("test_mode") is True


# ---- beta/testers CRUD (admin only, phone normalization) ----

class TestBetaTestersCRUD:
    TEST_PHONE_LOCAL = "0677665544"
    TEST_PHONE_NORM = "+33677665544"

    def test_list_admin(self, tokens):
        r = requests.get(f"{BASE_URL}/api/beta/testers", headers=_auth(tokens["admin"]))
        assert r.status_code == 200
        data = r.json()
        testers = data if isinstance(data, list) else data.get("testers", data.get("items", []))
        phones = [t.get("phone") if isinstance(t, dict) else t for t in testers]
        assert "+33688776655" in phones
        assert "+33688776656" in phones

    def test_list_forbidden_for_nontester(self, tokens):
        r = requests.get(f"{BASE_URL}/api/beta/testers", headers=_auth(tokens["nontester"]))
        assert r.status_code == 403

    def test_list_forbidden_for_beta(self, tokens):
        r = requests.get(f"{BASE_URL}/api/beta/testers", headers=_auth(tokens["beta1"]))
        assert r.status_code == 403

    def test_add_and_normalize_and_remove(self, tokens):
        # add
        r = requests.post(
            f"{BASE_URL}/api/beta/testers",
            headers=_auth(tokens["admin"]),
            json={"phone": self.TEST_PHONE_LOCAL},
        )
        assert r.status_code in (200, 201), r.text
        # invalid
        r = requests.post(
            f"{BASE_URL}/api/beta/testers",
            headers=_auth(tokens["admin"]),
            json={"phone": "123"},
        )
        assert r.status_code in (400, 422), r.text
        # list contains normalized
        r = requests.get(f"{BASE_URL}/api/beta/testers", headers=_auth(tokens["admin"]))
        assert r.status_code == 200
        data = r.json()
        testers = data if isinstance(data, list) else data.get("testers", data.get("items", []))
        phones = [t.get("phone") if isinstance(t, dict) else t for t in testers]
        assert self.TEST_PHONE_NORM in phones, phones
        # remove (cleanup)
        r = requests.delete(
            f"{BASE_URL}/api/beta/testers/{self.TEST_PHONE_NORM}",
            headers=_auth(tokens["admin"]),
        )
        assert r.status_code in (200, 204), r.text


# ---- reports geofence + is_test ----

class TestReportsGeofence:
    RENNES = (48.11, -1.68)  # inland
    OCEAN = (47.45, -3.05)

    def _ensure_test_mode(self, token, enabled):
        requests.post(
            f"{BASE_URL}/api/beta/test-mode", headers=_auth(token), json={"enabled": enabled}
        )

    def _payload(self, lat, lon, description="TEST_iter90"):
        return {
            "type": "obstacle_nav",
            "lat": lat,
            "lng": lon,
            "description": description,
        }

    def test_land_report_rejected_without_test_mode(self, tokens):
        self._ensure_test_mode(tokens["beta1"], False)
        r = requests.post(
            f"{BASE_URL}/api/reports",
            headers=_auth(tokens["beta1"]),
            json=self._payload(*self.RENNES),
        )
        assert r.status_code == 422, f"expected 422 land no-test got {r.status_code}: {r.text}"

    def test_land_report_ok_with_test_mode(self, tokens):
        self._ensure_test_mode(tokens["beta1"], True)
        r = requests.post(
            f"{BASE_URL}/api/reports",
            headers=_auth(tokens["beta1"]),
            json=self._payload(*self.RENNES, description="TEST_iter90_land"),
        )
        assert r.status_code in (200, 201), f"expected 200 got {r.status_code}: {r.text}"
        d = r.json()
        assert d.get("is_test") is True, d
        rid = d.get("id") or d.get("report_id")
        # cleanup
        requests.delete(
            f"{BASE_URL}/api/reports/{rid}", headers=_auth(tokens["admin"])
        )

    def test_ocean_report_nontester_no_flag(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/reports",
            headers=_auth(tokens["nontester"]),
            json=self._payload(*self.OCEAN, description="TEST_iter90_ocean"),
        )
        assert r.status_code in (200, 201), f"expected 200 ocean got {r.status_code}: {r.text}"
        d = r.json()
        assert not d.get("is_test"), d
        rid = d.get("id") or d.get("report_id")
        # cleanup
        requests.delete(
            f"{BASE_URL}/api/reports/{rid}", headers=_auth(tokens["nontester"])
        )

    def test_test_report_keeps_is_test_on_get(self, tokens):
        """23/07/2026 — l'ancien signalement « fixture » (id en dur) a été
        purgé le 10/07 : on crée un signalement de test et on vérifie que
        is_test SURVIT à la relecture GET /api/reports/{id}."""
        self._ensure_test_mode(tokens["beta1"], True)
        r = requests.post(
            f"{BASE_URL}/api/reports",
            headers=_auth(tokens["beta1"]),
            json=self._payload(*self.RENNES, description="TEST_iter90_roundtrip"),
        )
        assert r.status_code in (200, 201), r.text
        rid = r.json().get("id") or r.json().get("report_id")
        try:
            g = requests.get(
                f"{BASE_URL}/api/reports/{rid}", headers=_auth(tokens["beta1"]),
            )
            assert g.status_code == 200, g.text
            assert g.json().get("is_test") is True, g.json()
        finally:
            requests.delete(
                f"{BASE_URL}/api/reports/{rid}", headers=_auth(tokens["admin"])
            )


# ---- dev/test-accounts scope ----

class TestDevSwitchScope:
    def test_admin_sees_all(self, tokens):
        r = requests.get(f"{BASE_URL}/api/dev/test-accounts", headers=_auth(tokens["admin"]))
        assert r.status_code == 200
        data = r.json()
        accounts = data if isinstance(data, list) else data.get("accounts", data.get("items", []))
        emails_or_phones = " ".join(str(a) for a in accounts)
        # Admin should see admin + at least one beta
        assert "+33688776655" in emails_or_phones or "0688776655" in emails_or_phones \
            or "BetaTest1" in emails_or_phones

    def test_beta_sees_only_beta(self, tokens):
        r = requests.get(f"{BASE_URL}/api/dev/test-accounts", headers=_auth(tokens["beta1"]))
        assert r.status_code == 200
        data = r.json()
        accounts = data if isinstance(data, list) else data.get("accounts", data.get("items", []))
        joined = " ".join(str(a) for a in accounts)
        assert "+33760071445" not in joined and "0760071445" not in joined, \
            f"beta must not see admin: {joined}"
        assert "+33688776655" in joined or "0688776655" in joined or "BetaTest1" in joined

    def test_nontester_forbidden(self, tokens):
        r = requests.get(f"{BASE_URL}/api/dev/test-accounts", headers=_auth(tokens["nontester"]))
        assert r.status_code == 403


class TestDevSwitchTarget:
    def _fetch_uid(self, token, needle):
        r = requests.get(f"{BASE_URL}/api/dev/test-accounts", headers=_auth(token))
        assert r.status_code == 200
        for a in r.json().get("accounts", []):
            hay = f"{a.get('phone','')} {a.get('email','')} {a.get('pseudo','')}"
            if needle in hay:
                return a["user_id"]
        return None

    def test_beta_to_beta_ok(self, tokens):
        # beta1 -> beta2 via user_id
        uid = self._fetch_uid(tokens["beta1"], "+33688776656")
        assert uid, "beta2 must be visible in beta1's scope"
        r = requests.post(
            f"{BASE_URL}/api/dev/switch-account",
            headers=_auth(tokens["beta1"]),
            json={"target_user_id": uid},
        )
        assert r.status_code == 200, r.text
        assert "token" in r.json()

    def test_beta_to_admin_404(self, tokens):
        # Get admin user_id via admin scope
        admin_uid = None
        r = requests.get(f"{BASE_URL}/api/dev/test-accounts", headers=_auth(tokens["admin"]))
        for a in r.json().get("accounts", []):
            if "+33760071445" in (a.get("phone") or ""):
                admin_uid = a["user_id"]
                break
        assert admin_uid, "admin uid must be resolvable"
        # beta1 tries to switch to admin -> 404 (scope excludes admin)
        r = requests.post(
            f"{BASE_URL}/api/dev/switch-account",
            headers=_auth(tokens["beta1"]),
            json={"target_user_id": admin_uid},
        )
        assert r.status_code == 404, f"expected 404 got {r.status_code}: {r.text}"
