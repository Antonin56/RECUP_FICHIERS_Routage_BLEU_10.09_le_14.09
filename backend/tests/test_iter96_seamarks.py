"""
Iter96 — Balisage IALA zone A dans le moteur + arrondi des virages +
fenêtre route réductible (backend : contraintes seamarks).
"""
import os

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://engine-e-crouesty.preview.emergentagent.com",
).rstrip("/")
QA = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    s.headers.update(QA)
    s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": "0760071445"})
    r = s.post(f"{BASE_URL}/api/auth/otp/verify", json={"phone": "0760071445", "code": "123456"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _compute(token, start, end, **kw):
    return requests.post(
        f"{BASE_URL}/api/routes/compute",
        json={"start": start, "end": end,
              "draft_m": kw.get("draft_m", 1.5),
              "depth_margin_m": kw.get("depth_margin_m", 0.5),
              "lateral_margin_m": kw.get("lateral_margin_m", 100)},
        headers={"Authorization": f"Bearer {token}", **QA},
    )


def test_entrance_to_arradon_with_buoyage(token):
    """L'entrée du Golfe (goulet balisé dense) reste franchissable avec les
    contraintes IALA actives."""
    r = _compute(token, {"lat": 47.543, "lng": -2.921}, {"lat": 47.617, "lng": -2.828})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["waypoints"]) > 5           # trajet non trivial
    # Tolérance 0.25 m : l'arrondi des virages est validé sur le masque
    # DÉCIMÉ (~30 m) ; la grille pleine résolution (20 m) peut être quelques
    # cm sous le seuil (couvert par la marge utilisateur + warning API).
    assert d["min_depth_m"] >= d["threshold_m"] - 0.25
    # 22/07/2026 (iter103) : directions IALA par couples + couloirs entre paires
    # → trajet moins détourné dans le goulet (8,4 km vs 9,3 km avant), profondeur
    # et écarts réglementaires inchangés. Borne basse ajustée (ligne droite ≈ 8 km).
    assert 8000 < d["distance_m"] < 16000


def test_corner_rounding_adds_intermediate_points(token):
    """L'arrondi des virages produit plus de waypoints que le simple
    string-pulling (chaque angle coupé ajoute des points)."""
    r = _compute(token, {"lat": 47.617, "lng": -2.828}, {"lat": 47.50, "lng": -2.95},
                 lateral_margin_m=50)
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["waypoints"]) >= 8


def test_quiberon_houat_still_ok(token):
    r = _compute(token, {"lat": 47.47, "lng": -3.05}, {"lat": 47.385, "lng": -2.945},
                 draft_m=2.0, depth_margin_m=1.0, lateral_margin_m=200)
    assert r.status_code == 200, r.text
