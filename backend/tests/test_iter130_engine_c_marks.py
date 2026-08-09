"""SignalMar — Itér. 130 (03/08/2026) : CÔTÉ DE PASSAGE, retour armateur.

Deux anomalies signalées sur le Moteur C après la mise en service :

1. **« Illur » toujours du mauvais côté** — cause : le point de contournement
   était inséré entre deux waypoints de l'A* espacés de plusieurs kilomètres,
   déroutant tout le tronçon (rejeté par le contrôle de couloir) ; et lorsque
   le pontage conservait le même nombre de points, la reconstruction du
   résultat était sautée (`len(new) != len(old)`), donc le tracé restait
   INCHANGÉ alors que la balise était annoncée corrigée.
2. **Cardinale sud « Drenec » non respectée** — cause : le Moteur C ne gérait
   QUE les latérales rouge/verte ; les 545 cardinales de l'index étaient
   ignorées par la règle de côté, et le contrôle de validation d'un
   contournement (héritié de la passe 3) ne vérifie ni les cardinales ni le
   côté des autres latérales.

Ce fichier verrouille les deux règles + les garde-fous anti-fausse-alerte.
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

# Cardinale SUD « Drenec » (Golfe du Morbihan) : à laisser au SUD, le danger
# (banc découvrant vers l'île d'Ilur) est au NORD.
DRENEC = {"lat": 47.5734652, "lng": -2.8068735,
          "category": "south", "kind": "cardinal", "id": 900001, "name": "Drenec"}
# Cardinale NORD du chenal d'Arradon : roche à ~30 m au SUD seulement.
ARRADON_N = {"lat": 47.6104, "lng": -2.83645,
             "category": "north", "kind": "cardinal", "id": 900002, "name": "cardN"}
# Latérale VERTE « Illur » (isolée, sans paire) et paire serrée du chenal
# d'Arradon (65 m d'écartement).
ILLUR = {"lat": 47.5827118, "lng": -2.7951316,
         "category": "starboard", "kind": "lateral", "name": "Illur"}

# Itinéraires du Golfe traversant les chenaux d'Illur / d'Arradon.
GOLFE_PAIRS = [
    ({"lat": 47.5455, "lng": -2.9185}, {"lat": 47.5940, "lng": -2.7830}),   # Port-Navalo → Le Hézo
    ({"lat": 47.5455, "lng": -2.9185}, {"lat": 47.5870, "lng": -2.7820}),   # Port-Navalo → Ilur E
    ({"lat": 47.5580, "lng": -2.8560}, {"lat": 47.5870, "lng": -2.7820}),   # Kerners → Ilur E
    ({"lat": 47.5860, "lng": -2.8960}, {"lat": 47.5870, "lng": -2.7820}),   # Larmor-Baden → Ilur E
    ({"lat": 47.5455, "lng": -2.9185}, {"lat": 47.6165, "lng": -2.8230}),   # Port-Navalo → Arradon
    ({"lat": 47.6010, "lng": -2.7960}, {"lat": 47.5455, "lng": -2.9185}),   # Île d'Arz → Port-Navalo
]


@pytest.fixture(scope="module")
def admin() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": ADMIN_PHONE})
    assert r.status_code == 200, r.text[:200]
    r = s.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"phone": ADMIN_PHONE, "code": OTP_CODE,
              "pseudo": f"QAiter130_{uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 200, r.text[:200]
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


def _compute(session, start, end, engine_id="engine_c") -> dict:
    r = session.post(
        f"{BASE_URL}/api/routes/compute",
        json={"start": start, "end": end, "draft_m": 1.0, "depth_margin_m": 0.5,
              "use_tide": False, "engine_id": engine_id},
        timeout=180,
    )
    assert r.status_code == 200, f"{engine_id} → {r.status_code} {r.text[:300]}"
    return r.json()


# ── RÈGLE DES CARDINALES (unitaire, tracés synthétiques) ──────────────────
def _straight_track(mark, offset_north_m):
    """Tracé est-ouest passant à ``offset_north_m`` de la balise."""
    from core.bathy import M_PER_DEG_LAT
    lat = mark["lat"] + offset_north_m / M_PER_DEG_LAT
    return [(lat, mark["lng"] - 0.010), (lat, mark["lng"] + 0.010)]


def _audit(track, marks):
    from core.bathy import get_grid, m_per_deg_lng
    from core.nav_rules import merge_params
    from core.routing_engines.algos.signalmar_v3.direction import grid_for
    from core.routing_engines.algos.signalmar_v3.side import audit_sides
    return audit_sides(
        track, mlng=m_per_deg_lng(track[0][0]), params=merge_params(None),
        marks=marks, dir_grid=grid_for(track[0], track[-1]),
        depth_gate=(get_grid(), 1.0 + 0.5 + 2.0),
    )


@pytest.mark.parametrize("offset_m", [80.0, 150.0, 200.0])
def test_south_cardinal_wrong_side_is_detected(offset_m):
    """Passer au NORD de la cardinale SUD « Drenec » (côté danger) est une
    violation dès qu'on est dans la portée du haut-fond signalé."""
    viol = _audit(_straight_track(DRENEC, offset_m), [DRENEC])
    assert viol, f"violation attendue à {offset_m} m au nord de Drenec"
    assert viol[0]["name"] == "Drenec"
    assert viol[0]["kind"] == "cardinal"
    assert viol[0]["side_required"] == "au sud"


@pytest.mark.parametrize("offset_m", [-80.0, -150.0, -300.0])
def test_south_cardinal_right_side_is_clean(offset_m):
    """Passer au SUD de « Drenec » (côté sain) ne déclenche rien."""
    assert not _audit(_straight_track(DRENEC, offset_m), [DRENEC])


def test_cardinal_interdiction_stops_beyond_the_shoal_it_marks():
    """Le demi-disque forfaitaire de 300 m produisait des interdictions
    abusives : au sud de la cardinale nord d'Arradon il y a 12 à 14 m de fond
    dès 100 m. L'interdiction s'arrête à la portée du haut-fond + 80 m."""
    from core.bathy import get_grid
    from core.routing_engines.algos.signalmar_v3.side import _cardinal_reach_m

    gate = (get_grid(), 3.5)
    reach_arradon = _cardinal_reach_m(ARRADON_N, gate, 300.0)
    reach_drenec = _cardinal_reach_m(DRENEC, gate, 300.0)
    assert reach_arradon is not None and reach_drenec is not None
    assert reach_arradon < reach_drenec, (
        "le haut-fond d'Arradon est LOCAL (~30 m), celui de Drenec s'étend "
        f"beaucoup plus loin : {reach_arradon} vs {reach_drenec}")
    assert _audit(_straight_track(ARRADON_N, -60.0), [ARRADON_N]), \
        "60 m au sud d'une roche à 30 m doit rester une violation"
    assert not _audit(_straight_track(ARRADON_N, -200.0), [ARRADON_N]), \
        "200 m au sud, en 8-14 m de fond, ne doit PAS être signalé"


def test_tight_channel_pair_does_not_impose_its_side_from_outside():
    """Une latérale APPAIRÉE n'impose son côté que si le tracé emprunte la
    porte : la paire du chenal d'Arradon est écartée de 65 m, une route
    passant à 106 m n'y est pas (fausse alerte du 03/08)."""
    from core.nav_rules import merge_params
    from core.routing_engines.algos.signalmar_v3.side import _influence_m

    params = merge_params(None)
    green = dict(ILLUR)
    green["_pair"] = {"lat": 47.6129746, "lng": -2.8255766}
    green.update({"lat": 47.6134407, "lng": -2.8250723})
    tight = _influence_m(green, params)
    assert tight < 106.0, f"porte serrée : influence attendue < 106 m, got {tight}"
    isolated = _influence_m(dict(ILLUR), params)
    assert isolated == params["lateral_influence_m"], \
        f"balise isolée : influence pleine attendue, got {isolated}"


# ── BALISAGE DE BOUT EN BOUT SUR LE GOLFE ─────────────────────────────────
@pytest.mark.parametrize("start,end", GOLFE_PAIRS)
def test_no_mark_left_on_the_wrong_side_across_the_gulf(admin, start, end):
    """Aucune balise (latérale OU cardinale) laissée du mauvais côté sur les
    itinéraires du Golfe — c'est la double anomalie du 03/08."""
    res = _compute(admin, start, end)
    wrong = res.get("wrong_side_marks") or []
    assert not wrong, (
        f"{start} → {end} : balises du mauvais côté {wrong}")


def test_illur_channel_is_actually_corrected(admin):
    """« Illur » (verte, isolée) doit être CORRIGÉE et le tracé réellement
    modifié — le bug du 03/08 annonçait la correction sans toucher au tracé."""
    sea = {"lat": 47.5580, "lng": -2.8560}
    land = {"lat": 47.5870, "lng": -2.7820}
    c = _compute(admin, sea, land, "engine_c")
    a = _compute(admin, sea, land, "engine_a")
    assert "Illur" in (c.get("side_fixed") or []), \
        f"« Illur » attendue dans side_fixed, got {c.get('side_fixed')}"
    assert not (c.get("wrong_side_marks") or [])
    geo_c = [(round(w["lat"], 6), round(w["lng"], 6)) for w in c["waypoints"]]
    geo_a = [(round(w["lat"], 6), round(w["lng"], 6)) for w in a["waypoints"]]
    assert geo_c != geo_a, \
        "le tracé du Moteur C doit DIFFÉRER de celui du Moteur A (contournement)"


def test_reversibility_holds_after_side_corrections(admin):
    """Les contournements de balises ne doivent pas casser la RÈGLE 1 :
    géométrie identique dans les deux sens."""
    sea = {"lat": 47.5580, "lng": -2.8560}
    land = {"lat": 47.5870, "lng": -2.7820}
    fwd = _compute(admin, sea, land)
    bwd = _compute(admin, land, sea)
    g1 = [(round(w["lat"], 6), round(w["lng"], 6)) for w in fwd["waypoints"]]
    g2 = list(reversed([(round(w["lat"], 6), round(w["lng"], 6))
                        for w in bwd["waypoints"]]))
    assert g1 == g2, f"géométrie non réversible : {len(g1)} vs {len(g2)} points"


def test_frozen_engines_untouched_by_the_cardinal_rule(admin):
    """Moteurs A et B GELÉS : la règle des cardinales du Moteur C ne doit pas
    modifier leurs réponses ni leur ajouter de champs."""
    sea = {"lat": 47.5580, "lng": -2.8560}
    land = {"lat": 47.5870, "lng": -2.7820}
    for engine_id, algo in (("engine_a", "signalmar.v1"), ("engine_b", "signalmar.v2")):
        res = _compute(admin, sea, land, engine_id)
        assert res["engine"]["algo"] == algo
        for key in ("side_fixed", "wrong_side_marks", "endpoint_cardinals",
                    "engine_rules", "leg_reasons"):
            assert key not in res, f"{engine_id} ne doit pas exposer {key}"
