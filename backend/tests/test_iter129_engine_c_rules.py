"""SignalMar — Itér. 129 (03/08/2026) : MOTEUR C (« signalmar.v3 »).

Verrouille les 4 règles de navigation demandées par l'armateur le 03/08 et
codifiées dans ``backend/config/navigation_rules.yaml`` :

1. BALISAGE (priorité absolue) — calcul TOUJOURS dans le sens conventionnel
   (mer → terre) ⇒ géométrie IDENTIQUE dans les deux sens ; rouges à bâbord,
   vertes à tribord (plus aucune estimation par gradient).
2. PROFONDEUR — la profondeur prime sur la distance.
3. MARGE LATÉRALE — 50 m par défaut, réductible à 20 m ; sous 20 m, tronçons
   ROUGES + avertissement.
4. JAMAIS D'ÉCHEC — aucun « Passage impossible » (tronçons rouges à la place).

NON-RÉGRESSION : les Moteurs A (signalmar.v1) et B (signalmar.v2) sont GELÉS
— leurs réponses doivent rester inchangées (le surcoût « profondeur » est une
contextvar neutre par défaut).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
ADMIN_PHONE = "0760071445"
OTP_CODE = "123456"

# Chenal d'Illur (est du Golfe du Morbihan) — cas de référence du 03/08 :
# le Moteur B passait du MAUVAIS CÔTÉ de la balise verte « Illur ».
ILLUR_SEA = {"lat": 47.5720, "lng": -2.8300}
ILLUR_LAND = {"lat": 47.5905, "lng": -2.7850}

# Départ « fragile » (~77 m du seuil) — sert au test « jamais d'échec ».
FRAGILE_START = {"lat": 47.302, "lng": -2.096}
FRAGILE_END = {"lat": 47.5614, "lng": -2.87473}


@pytest.fixture(scope="module")
def admin() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": ADMIN_PHONE})
    assert r.status_code == 200, r.text[:200]
    r = s.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"phone": ADMIN_PHONE, "code": OTP_CODE,
              "pseudo": f"QAiter129_{uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 200, r.text[:200]
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


def _compute(session, start, end, engine_id, **kw) -> dict:
    payload = {
        "start": start, "end": end,
        "draft_m": 1.0, "depth_margin_m": 0.5, "use_tide": False,
        "engine_id": engine_id, **kw,
    }
    r = session.post(f"{BASE_URL}/api/routes/compute", json=payload, timeout=120)
    assert r.status_code == 200, f"{engine_id} → {r.status_code} {r.text[:300]}"
    return r.json()


def _geom(res: dict) -> list[tuple[float, float]]:
    return [(round(w["lat"], 6), round(w["lng"], 6)) for w in res["waypoints"]]


# ── Règles publiées ───────────────────────────────────────────────────────
def test_rules_endpoint_publishes_the_four_rules(admin):
    r = admin.get(f"{BASE_URL}/api/routing/rules", timeout=30)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    rules = body["rules"]
    assert rules["applies_to"] == "signalmar.v3"
    for section in ("balisage", "profondeur", "marge_laterale", "jamais_d_echec"):
        assert section in rules, f"section {section} absente : {list(rules)}"
    params = body["params"]
    assert params["margin_default_m"] == 50.0
    assert params["margin_reduced_m"] == 20.0
    assert params["force_conventional_direction"] is True


def test_engine_c_is_seeded_and_bound_to_v3(admin):
    r = admin.get(f"{BASE_URL}/api/routing/engines", timeout=30)
    assert r.status_code == 200, r.text[:300]
    engines = {e["id"]: e for e in r.json()["engines"]}
    assert "engine_c" in engines, f"Moteur C absent : {list(engines)}"
    assert engines["engine_c"]["algo"] == "signalmar.v3"
    assert engines["engine_c"]["active"] is True
    # Moteurs A et B GELÉS sur leurs algos historiques.
    assert engines["engine_a"]["algo"] == "signalmar.v1"
    assert engines["engine_b"]["algo"] == "signalmar.v2"


# ── RÈGLE 1 : sens conventionnel + côté des balises ───────────────────────
def test_rule1_same_geometry_both_directions(admin):
    fwd = _compute(admin, ILLUR_SEA, ILLUR_LAND, "engine_c")
    bwd = _compute(admin, ILLUR_LAND, ILLUR_SEA, "engine_c")
    g1 = _geom(fwd)
    g2 = list(reversed(_geom(bwd)))
    assert g1 == g2, (
        "la géométrie doit être IDENTIQUE dans les deux sens : "
        f"{len(g1)} vs {len(g2)} points"
    )
    assert fwd["distance_m"] == bwd["distance_m"]
    # Un seul des deux sens est « retourné » (l'autre est le sens conventionnel).
    assert fwd["engine_rules"]["computed_reversed"] != bwd["engine_rules"]["computed_reversed"]
    assert fwd["engine_rules"]["conventional_direction"] == "mer_vers_terre"


def test_rule1_conventional_direction_goes_sea_to_land(admin):
    res = _compute(admin, ILLUR_LAND, ILLUR_SEA, "engine_c")
    er = res["engine_rules"]
    # Le point CÔTÉ MER du calcul est bien celui du large (sud-ouest du chenal).
    assert abs(er["sea_end"]["lat"] - ILLUR_SEA["lat"]) < 1e-4
    assert abs(er["land_end"]["lat"] - ILLUR_LAND["lat"]) < 1e-4


def test_rule1_no_lateral_left_on_the_wrong_side(admin):
    res = _compute(admin, ILLUR_SEA, ILLUR_LAND, "engine_c")
    wrong = res.get("wrong_side_marks") or []
    assert not wrong, f"balises du mauvais côté non corrigées : {wrong}"
    # Le cas « Illur » du 03/08 doit être explicitement corrigé.
    fixed = res.get("side_fixed") or []
    assert "Illur" in fixed, f"« Illur » attendu dans side_fixed, got {fixed}"


# ── RÈGLE 3 : marge latérale ──────────────────────────────────────────────
def test_rule3_lateral_margin_is_measured_and_reported(admin):
    res = _compute(admin, ILLUR_SEA, ILLUR_LAND, "engine_c")
    used = res.get("lateral_margin_used_m")
    assert used in (50.0, 20.0), f"marge utilisée attendue 50 ou 20 m, got {used}"
    legs = res.get("leg_margin_m")
    assert isinstance(legs, list) and len(legs) == len(res["waypoints"]) - 1, \
        f"une marge mesurée par tronçon attendue, got {legs}"
    # Tout tronçon sous 20 m doit être ROUGE avec son motif.
    for i, m in enumerate(legs):
        if m <= 20.0:
            assert i in (res.get("compromised_legs") or []), \
                f"tronçon {i} à {m} m de marge doit être rouge"
            assert (res.get("leg_reasons") or {}).get(str(i)) == "low_margin"


# ── RÈGLE 4 : jamais d'échec ──────────────────────────────────────────────
def test_rule4_never_fails_on_fragile_start(admin):
    res = _compute(admin, FRAGILE_START, FRAGILE_END, "engine_c")
    assert res.get("waypoints"), "un tracé doit TOUJOURS être rendu"
    assert res["engine"]["algo"] == "signalmar.v3"
    joined = " || ".join(res.get("warnings") or [])
    assert "Passage impossible" not in joined


def test_rule4_red_legs_carry_a_reason(admin):
    res = _compute(admin, FRAGILE_START, FRAGILE_END, "engine_c")
    red = res.get("compromised_legs") or []
    reasons = res.get("leg_reasons") or {}
    n_legs = len(res["waypoints"]) - 1
    for i in red:
        assert 0 <= i < n_legs, f"index de tronçon rouge hors bornes : {i}"
        assert reasons.get(str(i)) in ("shallow", "low_margin"), \
            f"motif manquant pour le tronçon {i} : {reasons.get(str(i))}"


# ── NON-RÉGRESSION Moteurs A et B (GELÉS) ─────────────────────────────────
@pytest.mark.parametrize("engine_id,algo", [
    ("engine_a", "signalmar.v1"),
    ("engine_b", "signalmar.v2"),
])
def test_frozen_engines_still_answer_with_their_own_algo(admin, engine_id, algo):
    res = _compute(admin, ILLUR_SEA, ILLUR_LAND, engine_id)
    assert res["engine"]["algo"] == algo
    # Les champs PROPRES au Moteur C ne doivent jamais apparaître sur A/B.
    for key in ("engine_rules", "leg_margin_m", "leg_reasons"):
        assert key not in res, f"{engine_id} ne doit pas exposer {key}"


def test_frozen_engine_a_is_deterministic_across_calls(admin):
    a1 = _compute(admin, ILLUR_SEA, ILLUR_LAND, "engine_a")
    a2 = _compute(admin, ILLUR_SEA, ILLUR_LAND, "engine_a")
    assert _geom(a1) == _geom(a2), "Moteur A doit rester déterministe"
