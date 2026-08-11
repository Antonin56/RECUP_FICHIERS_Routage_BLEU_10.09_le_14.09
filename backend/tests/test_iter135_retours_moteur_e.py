"""SignalMar — Itér. 135 (11/08/2026 soir) : retours armateur sur le MOTEUR E.

Captures armateur (route Port-Navalo → Le Crouesty, moteur E) :
* « Grand Mouton pas respectée » — la route frôlait la verte à 72 m côté EST
  (le chenal profond de Port-Navalo est à l'OUEST) : l'asymétrie proche était
  noyée (la bouée est posée SUR sa roche) → repli CHAMP LOINTAIN (le côté au
  chenal 100-200 m domine de ≥ 4 m) ;
* « balise bâbord No2 pas respectée » — passage à 127 m du mauvais côté : le
  plafond de densité (0,6 × voisine) utilisait le PARTENAIRE du couple et
  écrasait le rayon 0,8 × écartement ;
* « embardée à l'entrée du port » — dents de scie de ±40 m : deux balises
  quasi à la même abscisse produisaient deux points décalés opposés dans la
  chaîne de complétion → lissage (fenêtre 50 m, balise la plus proche de
  l'axe) ;
* non-régression Logoden (chenal de Vannes) : la réparation pleine résolution
  accepte désormais le candidat qui RÉDUIT la pénalité de mauvais côté
  (route au SUD de Logoden) au lieu de conserver l'original fautif.

Toutes les règles restent UNIVERSELLES (aucune exception de terrain).
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from core.seamarks import (  # noqa: E402
    ISOLATED_SIDE_BATHY, SIDE_ABSOLUTE, get_seamarks,
)

START = (47.57517422898507, -2.8806422077521003)   # large de Port-Navalo
END = (47.54185598400968, -2.8990867189961116)     # Le Crouesty (bassin)
GRAND_MOUTON = (47.5619945, -2.9137521)            # verte isolée (Q.G)
NO2 = (47.5376391, -2.9124922)                     # rouge du chenal (couple No1)
LOGODEN = (47.6112008, -2.8303268)                 # rouge (couple Holavre)

M_LAT = 110_574.0


def _mlng(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


def _closest(pts, lat, lng):
    from core.routing_engines.algos.signalmar_v2.standoff import _closest_on
    return _closest_on(pts, lat, lng, _mlng(lat))


@pytest.fixture(scope="module")
def eng():
    from core.routing_engines.algos.signalmar_v5 import SignalmarV5
    return SignalmarV5()


@pytest.fixture(scope="module")
def routes(eng):
    """Route armateur calculée à 3 hauteurs de marée (ZH, mi, haute)."""
    return {
        t: eng.compute_auto(START[0], START[1], END[0], END[1],
                            1.0, 0.5, 10.0, tide_m=t)
        for t in (0.0, 2.5, 5.0)
    }


# ── 1. Grand Mouton : champ lointain → côté OUEST (chenal profond) ───────
def test_grand_mouton_cote_ouest_confiant():
    sm = get_seamarks()
    m = min((x for x in sm.marks if x.get("kind") == "lateral"),
            key=lambda x: (x["lat"] - GRAND_MOUTON[0]) ** 2
            + (x["lng"] - GRAND_MOUTON[1]) ** 2)
    t1 = SIDE_ABSOLUTE.set(True); t2 = ISOLATED_SIDE_BATHY.set(True)
    try:
        w = sm.navigable_side(m)
        assert w is not None, "l'asymétrie champ lointain doit trancher"
        assert w[0] < -0.5, f"le chenal (24 m) est à l'OUEST, obtenu {w}"
        # Le mode gelé (Moteur D) ne voit PAS le repli champ lointain.
        assert "_navside_v5" in m and m.get("_navside") is not True
    finally:
        ISOLATED_SIDE_BATHY.reset(t2); SIDE_ABSOLUTE.reset(t1)


def test_grand_mouton_passee_a_l_ouest(routes):
    for t, r in routes.items():
        pts = [(w["lat"], w["lng"]) for w in r["waypoints"]]
        d, i, p = _closest(pts, *GRAND_MOUTON)
        if d > 600.0:
            continue
        assert p[1] < GRAND_MOUTON[1], (
            f"marée {t} : la route doit passer à l'OUEST de Grand Mouton "
            f"(chenal), passage à {d:.0f} m côté est")


# ── 2. No2 + aucune balise du mauvais côté, à toute marée ────────────────
def test_aucun_mauvais_cote_route_crouesty(routes):
    for t, r in routes.items():
        names = [v.get("name") for v in (r.get("wrong_side_marks") or [])]
        assert not names, f"marée {t} : mauvais côté détecté {names}"
        pts = [(w["lat"], w["lng"]) for w in r["waypoints"]]
        d, _i, _p = _closest(pts, *NO2)
        assert d > 155.0, (
            f"marée {t} : passage à {d:.0f} m de No2 — le demi-disque "
            "0,8 × écartement (159 m) doit tenir")


# ── 3. Embardée : pas de dents de scie sur le tronçon final ─────────────
def test_pas_d_embardee_entree_du_port(routes):
    for t, r in routes.items():
        pts = [(w["lat"], w["lng"]) for w in r["waypoints"]]
        # tronçon final (800 derniers mètres) : aucun demi-tour (virage
        # > 110°) entre segments consécutifs de plus de 25 m.
        tail: list[tuple[float, float]] = []
        acc = 0.0
        for k in range(len(pts) - 1, 0, -1):
            tail.insert(0, pts[k])
            acc += math.hypot((pts[k][0] - pts[k - 1][0]) * M_LAT,
                              (pts[k][1] - pts[k - 1][1]) * _mlng(pts[k][0]))
            if acc > 800.0:
                break
        tail.insert(0, pts[max(0, k - 1)])
        for a, b, c in zip(tail, tail[1:], tail[2:]):
            v1 = ((b[1] - a[1]) * _mlng(b[0]), (b[0] - a[0]) * M_LAT)
            v2 = ((c[1] - b[1]) * _mlng(b[0]), (c[0] - b[0]) * M_LAT)
            n1, n2 = math.hypot(*v1), math.hypot(*v2)
            if n1 < 25.0 or n2 < 25.0:
                continue
            cosang = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
            assert cosang > -0.35, (
                f"marée {t} : demi-tour ({math.degrees(math.acos(max(-1, min(1, cosang)))):.0f}°) "
                f"près de {b} — embardée")


# ── 4. Non-régression Logoden (réparation par pénalité de côté) ─────────
def test_logoden_au_sud_chenal_de_vannes(eng):
    r = eng.compute_auto(47.53214474552446, -2.92678544441799,
                         47.615738117406266, -2.8154603141514327,
                         1.5, 0.5, 10.0)
    names = [v.get("name") for v in (r.get("wrong_side_marks") or [])]
    assert not names, f"aucune balise du mauvais côté attendue, obtenu {names}"
    pts = [(w["lat"], w["lng"]) for w in r["waypoints"]]
    d, _i, p = _closest(pts, *LOGODEN)
    if d < 300.0:
        assert p[0] < LOGODEN[0], (
            f"la route doit passer au SUD de Logoden (rouge), passage à "
            f"{d:.0f} m au nord")
