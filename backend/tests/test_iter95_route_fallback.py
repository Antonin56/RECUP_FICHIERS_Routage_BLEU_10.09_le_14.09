"""
Iter95 — Bypass comptes de test : départ hors zone / à terre → remplacé par
Arradon (Golfe du Morbihan). Comptes normaux : refus inchangé (422).
"""
import os

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://calcul-optimize.preview.emergentagent.com",
).rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}
ADMIN_PHONE = "0760071445"        # compte dev/testeur
NORMAL_PHONE = "0699999999"       # compte normal (créé au besoin)

PARIS = {"lat": 48.85, "lng": 2.35}          # hors zone pilote
VANNES_TERRE = {"lat": 47.658, "lng": -2.760}  # dans la couverture, à terre
DEST_GOLFE = {"lat": 47.57, "lng": -2.85}

BODY = {"draft_m": 1.5, "depth_margin_m": 0.5, "lateral_margin_m": 50}


def _login(phone: str, pseudo: str | None = None) -> str:
    s = requests.Session()
    s.headers.update(QA)
    s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone})
    payload: dict = {"phone": phone, "code": "123456"}
    r = s.post(f"{BASE_URL}/api/auth/otp/verify", json=payload)
    if r.status_code != 200 and pseudo:
        s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone})
        r = s.post(f"{BASE_URL}/api/auth/otp/verify", json={**payload, "pseudo": pseudo})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _compute(token: str, start: dict):
    return requests.post(
        f"{BASE_URL}/api/routes/compute",
    # 03/08/2026 — moteur ÉPINGLÉ : ce test verrouille le comportement
    # HISTORIQUE (Moteur A / B). Le compte armateur utilise désormais le
    # Moteur C, dont les règles diffèrent volontairement (jamais d'échec,
    # marge 50/20 m propre, sens conventionnel forcé) : sans engine_id
    # explicite, l'API choisirait le moteur ACTIF du compte.
        json={"engine_id": "engine_a", "start": start, "end": DEST_GOLFE, **BODY},
        headers={"Authorization": f"Bearer {token}", **QA},
    )


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_PHONE)


@pytest.fixture(scope="module")
def normal_token():
    return _login(NORMAL_PHONE, pseudo="TestNormal")


def test_tester_start_out_of_zone_falls_back_to_arradon(admin_token):
    r = _compute(admin_token, PARIS)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["waypoints"][0] == {"lat": 47.61, "lng": -2.825}
    assert any("Arradon" in w for w in d["warnings"])


def test_tester_start_on_land_falls_back_to_nearest_water(admin_token):
    """23/07 (extension de zone) : départ à terre PRÈS de la côte → l'eau
    navigable la plus proche (≤ 5 km), plus Arradon systématique."""
    r = _compute(admin_token, VANNES_TERRE)
    assert r.status_code == 200, r.text
    d = r.json()
    w0 = d["waypoints"][0]
    assert (w0["lat"], w0["lng"]) != (VANNES_TERRE["lat"], VANNES_TERRE["lng"])
    assert any("remplacé par" in w for w in d["warnings"])


def test_normal_account_still_rejected(normal_token):
    r = _compute(normal_token, PARIS)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "out_of_coverage"


def test_tester_destination_out_of_zone_still_rejected(admin_token):
    """Le bypass ne concerne QUE le départ — destination hors zone = refus."""
    r = requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={"start": DEST_GOLFE, "end": PARIS, **BODY},
        headers={"Authorization": f"Bearer {admin_token}", **QA},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "out_of_coverage"
