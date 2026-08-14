"""Itération 137 (14/08/2026) — Moteur F : la cardinale ne scelle plus le
chenal balisé + signalement « balisage non respecté ».

Bugs armateur (captures 14/08) :
1. Route R-20260814-164055-B5 (Arradon → anse d'Arradon) : détour de ~1 km
   par le NORD au lieu du chenal court entre la « Truie d'Arradon » (rouge)
   et « Holavre » / « Le Druic » (vertes). Cause mesurée : le demi-disque
   « mauvais côté » (300 m) de la cardinale NORD située à 114 m de la Truie
   scellait l'entrée du chenal en maille grossière (le masque FIN était
   ouvert, fonds 4-15 m) → la passe grossière choisissait le nord et les
   fenêtres fines ne revisitaient jamais le chenal.
2. R-20260814-165115-CT (mêmes lieux à 11 min d'écart) divergeait (passage
   Les Rechauds → nord de la Truie) : même cause, sensibilité au départ.

Correctif (seamarks.rasterize_blocked, gated SIDE_ABSOLUTE_V6 — Moteur F
UNIQUEMENT) : le rayon « mauvais côté » d'une cardinale est plafonné à
0,9 × la distance à la latérale la plus proche (plancher 120 m historique) —
quand une latérale est proche, c'est ELLE qui fait autorité sur la limite
du chenal. Universel, aucune exception de terrain.
"""
import math

import pytest

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
from core.routing_engines.algos import get_algo
from core.seamarks import (
    ISOLATED_SIDE_BATHY, SIDE_ABSOLUTE, SIDE_ABSOLUTE_V6, get_seamarks,
)

B5 = ((47.61417599274132, -2.828185517975284),
      (47.58565138724609, -3.023353153422526))
CT = ((47.61277179048031, -2.8277441973977413),
      (47.586526229784155, -3.0234919203219373))
TRUIE = (47.6096615, -2.837503)     # latérale rouge
DRUIC = (47.6075123, -2.8341932)    # latérale verte (couple de la Truie)
HOLAVRE = (47.6062766, -2.8327661)
CARD_N = (47.6104, -2.83645)        # cardinale N à 114 m de la Truie


def _pts(res):
    return [(float(w["lat"]), float(w["lng"])) for w in res["waypoints"]]


def _closest(pts, lat, lng):
    """(dist_m, point le plus proche) du tracé à la balise."""
    mlng = m_per_deg_lng(lat)
    best, bp = 1e18, None
    for i in range(len(pts) - 1):
        ax = (pts[i][1] - lng) * mlng
        ay = (pts[i][0] - lat) * M_PER_DEG_LAT
        bx = (pts[i + 1][1] - lng) * mlng
        by = (pts[i + 1][0] - lat) * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        d = math.hypot(ax + t * dx, ay + t * dy)
        if d < best:
            best, bp = d, (ax + t * dx, ay + t * dy)
    return best, bp


@pytest.fixture(scope="module")
def res_b5():
    return get_algo("signalmar.v6").compute_auto(
        *B5[0], *B5[1], 1.0, 0.5, 10.0, tide_m=0.0)


@pytest.fixture(scope="module")
def res_ct():
    return get_algo("signalmar.v6").compute_auto(
        *CT[0], *CT[1], 1.0, 0.5, 10.0, tide_m=0.0)


def test_b5_prend_le_chenal_court(res_b5):
    """La route B5 faisait 23 602 m par le nord : elle doit repasser par le
    chenal Truie ↔ Druic/Holavre (nettement plus courte)."""
    assert res_b5["distance_m"] < 23100.0
    pts = _pts(res_b5)
    inchan = [p for p in pts
              if 47.604 <= p[0] <= 47.6094 and -2.841 <= p[1] <= -2.831]
    assert inchan, "aucun waypoint dans le chenal court Truie/Druic"


@pytest.mark.parametrize("fixname", ["res_b5", "res_ct"])
def test_passage_entre_truie_et_druic(fixname, request):
    """Consigne armateur : « la route aurait dû passer entre la Truie
    d'Arradon et Holavre ou Le Druic » — au SUD de la Truie (rouge), au
    NORD des vertes, sans frôlement ni mauvais côté."""
    res = request.getfixturevalue(fixname)
    pts = _pts(res)
    d_t, p_t = _closest(pts, *TRUIE)
    assert d_t <= 300.0, "la route doit emprunter la porte Truie/Druic"
    assert p_t[1] < 0.0, "le tracé doit passer au SUD de la Truie (rouge)"
    assert d_t >= 45.0
    d_d, p_d = _closest(pts, *DRUIC)
    assert p_d[1] > 0.0, "le tracé doit passer au NORD du Druic (verte)"
    assert d_d >= 45.0
    d_h, p_h = _closest(pts, *HOLAVRE)
    assert d_h < 60.0 and p_h[1] < 0.0 or p_h[1] > 0.0
    assert not (res.get("wrong_side_marks") or [])


def test_b5_ct_convergent(res_b5, res_ct):
    """Deux requêtes quasi identiques (départs à 160 m) ne divergent plus
    de corridor : les deux empruntent le chenal court."""
    for res in (res_b5, res_ct):
        pts = _pts(res)
        assert any(47.604 <= p[0] <= 47.6094 and -2.841 <= p[1] <= -2.831
                   for p in pts)
    assert abs(res_b5["distance_m"] - res_ct["distance_m"]) < 600.0


def test_cap_cardinale_seulement_en_mode_v6():
    """Le plafond du disque cardinal est STRICTEMENT gated SIDE_ABSOLUTE_V6 :
    hors mode F, le rayon 300 m historique s'applique (moteurs A-E figés)."""
    import numpy as np
    sm = get_seamarks()
    from core.bathy import get_grid
    grid = get_grid()
    mlng = m_per_deg_lng(TRUIE[0])
    # MAILLE GROSSIÈRE (100 m) : c'est là que la cardinale scellait le chenal
    # (en maille fine le couloir libre du couple ré-ouvrait la porte).
    # Fenêtre identique au diagnostic du 14/08 (alignement de grille inclus).
    step = 100.0
    lats = np.arange(47.618, 47.598, -step / M_PER_DEG_LAT)
    lngs = np.arange(-2.854, -2.822, step / mlng)
    D = np.array([[grid.depth_at(la, lo) or -99 for lo in lngs] for la in lats])
    # point à ~214 m au SSO de la cardinale, dans le chenal (fond 11 m)
    P = (47.6086, -2.8375)
    i = int(np.argmin(abs(lats - P[0])))
    j = int(np.argmin(abs(lngs - P[1])))
    tok1 = ISOLATED_SIDE_BATHY.set(True)
    tok2 = SIDE_ABSOLUTE.set(True)
    try:
        blk_e = sm.rasterize_blocked(lats, lngs, mlng, M_PER_DEG_LAT,
                                     min_depth=1.5, strict_depth=3.5, depth=D,
                                     strict_exempt=(B5[0], B5[1]))
        tok3 = SIDE_ABSOLUTE_V6.set(True)
        try:
            blk_f = sm.rasterize_blocked(lats, lngs, mlng, M_PER_DEG_LAT,
                                         min_depth=1.5, strict_depth=3.5,
                                         depth=D, strict_exempt=(B5[0], B5[1]))
        finally:
            SIDE_ABSOLUTE_V6.reset(tok3)
    finally:
        SIDE_ABSOLUTE.reset(tok2)
        ISOLATED_SIDE_BATHY.reset(tok1)
    assert bool(blk_e[i, j]) is True, "mode E : disque cardinal 300 m intact"
    assert bool(blk_f[i, j]) is False, "mode F : chenal ouvert (cap 0,9 × latérale)"


def test_moteur_e_b5_inchange():
    """Gel du Moteur E : B5 avec engine_e reprend le détour nord historique
    (~23,6 km) — aucune contamination par le correctif v6."""
    res = get_algo("signalmar.v5").compute_auto(
        *B5[0], *B5[1], 1.0, 0.5, 10.0, tide_m=0.0)
    assert res["distance_m"] > 23300.0
    pts = _pts(res)
    # le chenal SUD de la Truie (la porte Truie/Druic) n'est pas emprunté
    assert not any(47.604 <= p[0] <= 47.6094 and -2.841 <= p[1] <= -2.831
                   for p in pts)
