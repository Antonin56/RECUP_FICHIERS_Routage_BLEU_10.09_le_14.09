"""iter104 review — admin moderation deletion + clean DB (no test markers on land).

Bugs sous test :
  (1) admin (user_0b6070a69154) peut supprimer le signalement d'un AUTRE
      auteur (DELETE /api/reports/{id}) — attendu 200 {ok:true}.
  (2) un compte standard NON-auteur reçoit toujours 403.
  (3) GET /api/reports?lat=47.55&lng=-2.9&radius_km=500 (JWT admin) : plus
      de descriptions "TEST_*" / "iter*", plus de is_test:true, plus de
      marqueurs à des positions terrestres évidentes.
"""
from __future__ import annotations

import os
import random
import sys

import pytest
import requests

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")

from core.auth import make_jwt  # noqa: E402

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
BYPASS_HEADER = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
ADMIN_USER_ID = "user_0b6070a69154"
ADMIN_TOKEN = make_jwt(ADMIN_USER_ID)


# ── helpers ────────────────────────────────────────────────────────────────
def _rand_phone() -> str:
    return "0699" + "".join(random.choices("0123456789", k=6))


def _otp_login(phone: str, pseudo: str | None = None) -> tuple[str, dict]:
    """Return (token, user) after OTP request + verify."""
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"phone": phone},
        headers=BYPASS_HEADER,
        timeout=15,
    )
    assert r.status_code == 200, f"otp/request {r.status_code} {r.text}"
    payload: dict = {"phone": phone, "code": "123456"}
    if pseudo:
        payload["pseudo"] = pseudo
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json=payload,
        headers=BYPASS_HEADER,
        timeout=15,
    )
    assert r.status_code == 200, f"otp/verify {r.status_code} {r.text}"
    d = r.json()
    return d["token"], d["user"]


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}", **BYPASS_HEADER}


# ── fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def standard_user_a() -> tuple[str, dict]:
    """Standard user, will create the report deleted by admin."""
    return _otp_login(_rand_phone(), pseudo=f"QAdelA{random.randint(100,999)}")


@pytest.fixture(scope="module")
def standard_user_b() -> tuple[str, dict]:
    """Second standard user — should get 403 when deleting A's report."""
    return _otp_login(_rand_phone(), pseudo=f"QAdelB{random.randint(100,999)}")


# ── T1 admin moderation delete ─────────────────────────────────────────────
class TestAdminModerationDelete:
    def test_admin_can_delete_other_authors_report(self, standard_user_a):
        token_a, _ua = standard_user_a
        headers_a = {"Authorization": f"Bearer {token_a}", **BYPASS_HEADER}
        # Créer signalement en mer (Belle-Île sud ~47.30,-3.10 open sea)
        r = requests.post(
            f"{BASE_URL}/api/reports",
            headers=headers_a,
            json={
                "type": "obstacle_nav",
                "lat": 47.30,
                "lng": -3.10,
                "description": "iter104 moderation delete target",
            },
            timeout=15,
        )
        assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
        rid = r.json()["id"]

        # Admin delete
        r = requests.delete(
            f"{BASE_URL}/api/reports/{rid}", headers=_admin_headers(), timeout=15
        )
        assert r.status_code == 200, f"admin delete: {r.status_code} {r.text}"
        assert r.json().get("ok") is True

        # Verify gone
        r = requests.get(
            f"{BASE_URL}/api/reports/{rid}", headers=_admin_headers(), timeout=15
        )
        assert r.status_code == 404

    def test_non_author_standard_gets_403(self, standard_user_a, standard_user_b):
        token_a, _ua = standard_user_a
        token_b, _ub = standard_user_b
        h_a = {"Authorization": f"Bearer {token_a}", **BYPASS_HEADER}
        h_b = {"Authorization": f"Bearer {token_b}", **BYPASS_HEADER}
        # A creates report
        r = requests.post(
            f"{BASE_URL}/api/reports",
            headers=h_a,
            json={
                "type": "obstacle_nav",
                "lat": 47.32,
                "lng": -3.12,
                "description": "iter104 non-author 403 target",
            },
            timeout=15,
        )
        assert r.status_code == 200
        rid = r.json()["id"]
        try:
            # B tries to delete → 403
            r = requests.delete(
                f"{BASE_URL}/api/reports/{rid}", headers=h_b, timeout=15
            )
            assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text}"
        finally:
            # Cleanup via admin
            requests.delete(
                f"{BASE_URL}/api/reports/{rid}",
                headers=_admin_headers(),
                timeout=15,
            )


# ── T2 clean DB ────────────────────────────────────────────────────────────
class TestDatabaseCleanliness:
    """Aucun signalement de test / positions terrestres évidentes ne doit
    persister dans la zone Golfe/Morbihan."""

    LAND_POINTS = [
        (48.11, -1.68, "Rennes"),
        (43.29, 5.36, "Marseille"),
        (47.50, -2.80, "Presqu'île de Rhuys"),
    ]

    def test_no_test_markers_in_reports_list(self):
        r = requests.get(
            f"{BASE_URL}/api/reports",
            headers=_admin_headers(),
            params={"lat": 47.55, "lng": -2.9, "radius_km": 500},
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        reports = r.json()
        assert isinstance(reports, list)

        offenders_desc: list[dict] = []
        offenders_flag: list[dict] = []
        offenders_land: list[dict] = []

        for rep in reports:
            desc = (rep.get("description") or "").strip()
            desc_low = desc.lower()
            if desc.startswith("TEST_") or desc_low.startswith("iter"):
                offenders_desc.append(
                    {"id": rep.get("id"), "desc": desc[:80], "lat": rep.get("lat"), "lng": rep.get("lng")}
                )
            if rep.get("is_test") is True:
                offenders_flag.append(
                    {"id": rep.get("id"), "desc": desc[:80], "lat": rep.get("lat"), "lng": rep.get("lng")}
                )
            for lat_l, lng_l, name in self.LAND_POINTS:
                try:
                    dlat = float(rep.get("lat")) - lat_l
                    dlng = float(rep.get("lng")) - lng_l
                except Exception:
                    continue
                # ~ within 0.02° (~2 km) of the reference land point
                if abs(dlat) < 0.02 and abs(dlng) < 0.02:
                    offenders_land.append(
                        {"id": rep.get("id"), "near": name, "lat": rep.get("lat"), "lng": rep.get("lng")}
                    )
                    break

        # Report all offenders together for diagnostics
        problems = {
            "descriptions_TEST_or_iter": offenders_desc,
            "is_test_true": offenders_flag,
            "on_land_points": offenders_land,
        }
        assert (
            not offenders_desc
            and not offenders_flag
            and not offenders_land
        ), f"Dirty DB: {problems}"
