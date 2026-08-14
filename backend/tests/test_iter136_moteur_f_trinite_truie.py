"""Itération 136 (13/08/2026) — MOTEUR F (signalmar.v6) : respect des balises.

Bugs armateur (captures 13/08, route R-20260813-144317-MX, Arradon →
La Trinité, marge 30 m, tirant+marge 1,5 m, marée 0) :
1. « Truie d'Arradon » (rouge) recoupée à 165 m du MAUVAIS côté malgré
   l'avertissement ;
2. balises du chenal de La Trinité non respectées (N°4 frôlée à 0,7 m,
   N°8 à 129 m du mauvais côté, trajectoire en Z, arrivée manquée de 98 m
   sans signalement).

Le Moteur E est FIGÉ au 13/08 : ses résultats ne changent PAS (le bug de la
Truie y reste — preuve de gel). Les corrections vivent dans signalmar.v6
(sidefix + complétion disciplinée), gardées par SIDE_ABSOLUTE_V6.
"""
import math

import pytest

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
from core.routing_engines.algos import ALGO_REGISTRY, get_algo
from core.seamarks import get_seamarks

START = (47.61270864146456, -2.8246830304036523)   # départ Arradon (Kerrat)
END_MX = (47.583795787592805, -3.0213006511557983)  # arrivée La Trinité (MX)
END_Z = (47.5855, -3.0235)                          # arrivée + profonde (Z 11/08)
DRAFT, DM, LM = 1.0, 0.5, 30.0

TRUIE = (4511415482, "Truie d'Arradon")


def _pts(res):
    return [(float(w["lat"]), float(w["lng"])) for w in res["waypoints"]]


def _closest_m(pts, lat, lng):
    mlng = m_per_deg_lng(lat)
    best = 1e18
    for i in range(len(pts) - 1):
        ax = (pts[i][1] - lng) * mlng
        ay = (pts[i][0] - lat) * M_PER_DEG_LAT
        bx = (pts[i + 1][1] - lng) * mlng
        by = (pts[i + 1][0] - lat) * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def _hairpins(pts, thr=100.0):
    out = []
    for i in range(1, len(pts) - 1):
        mlng = m_per_deg_lng(pts[i][0])
        v1 = ((pts[i][1] - pts[i - 1][1]) * mlng,
              (pts[i][0] - pts[i - 1][0]) * M_PER_DEG_LAT)
        v2 = ((pts[i + 1][1] - pts[i][1]) * mlng,
              (pts[i + 1][0] - pts[i][0]) * M_PER_DEG_LAT)
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 < 1.0 or n2 < 1.0:
            continue
        cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
        ang = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
        if ang > thr:
            out.append((i, round(ang)))
    return out


def _side_of_truie(pts):
    """+1 si le tracé passe du côté REQUIS de la Truie (ESE/chenal)."""
    sm = get_seamarks()
    m = next(x for x in sm.marks if x["id"] == TRUIE[0])
    from core.seamarks import ISOLATED_SIDE_BATHY, SIDE_ABSOLUTE
    t1 = ISOLATED_SIDE_BATHY.set(True)
    t2 = SIDE_ABSOLUTE.set(True)
    try:
        de, dn = sm.mark_dir_confident(m)
    finally:
        SIDE_ABSOLUTE.reset(t2)
        ISOLATED_SIDE_BATHY.reset(t1)
    u = (dn, -de)  # rouge : tribord de D
    mlng = m_per_deg_lng(m["lat"])
    best, bp = 1e18, None
    for i in range(len(pts) - 1):
        ax = (pts[i][1] - m["lng"]) * mlng
        ay = (pts[i][0] - m["lat"]) * M_PER_DEG_LAT
        bx = (pts[i + 1][1] - m["lng"]) * mlng
        by = (pts[i + 1][0] - m["lat"]) * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px, py)
        if d < best:
            best, bp = d, (px, py)
    return (1 if bp[0] * u[0] + bp[1] * u[1] > 0 else -1), best


@pytest.fixture(scope="module")
def res_f_mx():
    return get_algo("signalmar.v6").compute_auto(
        *START, *END_MX, DRAFT, DM, LM, tide_m=0.0)


@pytest.fixture(scope="module")
def res_e_mx():
    return get_algo("signalmar.v5").compute_auto(
        *START, *END_MX, DRAFT, DM, LM, tide_m=0.0)


@pytest.fixture(scope="module")
def res_f_z():
    return get_algo("signalmar.v6").compute_auto(
        *START, *END_Z, DRAFT, DM, LM, tide_m=0.0)


def test_registry_a_signalmar_v6():
    assert "signalmar.v6" in ALGO_REGISTRY
    algo = get_algo("signalmar.v6")
    assert algo.id == "signalmar.v6"
    assert algo.version.startswith("6.")


def test_moteur_e_fige_conserve_son_bug_truie(res_e_mx):
    """PREUVE DE GEL : le Moteur E rend toujours la Truie du mauvais côté
    (165 m) avec son avertissement — comportement du 13/08 inchangé."""
    names = [v.get("name") for v in (res_e_mx.get("wrong_side_marks") or [])]
    assert TRUIE[1] in names
    side, dist = _side_of_truie(_pts(res_e_mx))
    assert side == -1 and 120.0 <= dist <= 220.0


def test_f_truie_du_bon_cote(res_f_mx):
    side, dist = _side_of_truie(_pts(res_f_mx))
    assert side == 1, "la Truie d'Arradon doit être laissée à bâbord (chenal au SE)"
    assert dist >= 60.0
    assert not (res_f_mx.get("wrong_side_marks") or [])


def test_f_aucun_avertissement_mauvais_cote_ni_frolement(res_f_mx):
    warns = res_f_mx.get("warnings") or []
    assert not any(w.startswith("⚠ MAUVAIS CÔTÉ") for w in warns)
    assert not any(w.startswith("⚠ La route passe à ~") for w in warns)


def test_f_chenal_trinite_respecte(res_f_mx):
    """N°4 n'est plus frôlée (0,7 m avant) et les balises du chenal sont
    passées à distance saine."""
    sm = get_seamarks()
    pts = _pts(res_f_mx)
    for name, dmin in (("N°4", 40.0), ("N°6", 40.0), ("N°8", 40.0),
                       ("N°10", 40.0), ("Dalh", 40.0), ("N°12", 40.0)):
        m = next(x for x in sm.marks
                 if x.get("name") == name
                 and 47.56 <= x["lat"] <= 47.60 and -3.04 <= x["lng"] <= -2.99)
        d = _closest_m(pts, m["lat"], m["lng"])
        assert d >= dmin, f"{name} frôlée à {d:.0f} m (mini {dmin})"


def test_f_arrivee_atteinte_exactement(res_f_mx):
    pts = _pts(res_f_mx)
    d = math.hypot((pts[-1][0] - END_MX[0]) * M_PER_DEG_LAT,
                   (pts[-1][1] - END_MX[1]) * m_per_deg_lng(END_MX[0]))
    assert d < 5.0, f"arrivée manquée de {d:.0f} m (98 m avant le correctif)"
    assert not res_f_mx.get("end_snapped")


def test_f_pas_de_trajectoire_en_z(res_f_mx, res_f_z):
    assert _hairpins(_pts(res_f_mx)) == []
    assert _hairpins(_pts(res_f_z)) == []


def test_f_route_z_arrivee_et_balises(res_f_z):
    pts = _pts(res_f_z)
    d = math.hypot((pts[-1][0] - END_Z[0]) * M_PER_DEG_LAT,
                   (pts[-1][1] - END_Z[1]) * m_per_deg_lng(END_Z[0]))
    assert d < 5.0
    assert not (res_f_z.get("wrong_side_marks") or [])
    sm = get_seamarks()
    m12 = next(x for x in sm.marks if x.get("name") == "N°12"
               and 47.58 <= x["lat"] <= 47.59)
    assert _closest_m(pts, m12["lat"], m12["lng"]) >= 40.0


def test_f_fond_jamais_degrade(res_f_mx, res_e_mx):
    """Le correctif n'abaisse pas le pire fond du tracé (filet de sécurité)."""
    assert res_f_mx["min_depth_m"] >= res_e_mx["min_depth_m"] - 0.05


def test_f_illur_nord_2_sens_comme_d_et_e():
    """Non-régression zone pilote : la verte isolée Illur reste passée au
    NORD dans les deux sens (référence Moteur D/E, iter133)."""
    algo = get_algo("signalmar.v6")
    ILLUR = (47.5827118, -2.7951316)
    for a, b in (((47.5455, -2.9185), (47.5870, -2.7820)),
                 ((47.5870, -2.7820), (47.5455, -2.9185))):
        r = algo.compute_auto(*a, *b, 1.5, 0.5, 50.0)
        pts = _pts(r)
        d = _closest_m(pts, *ILLUR)
        # côté : le point le plus proche doit être AU NORD de la balise
        mlng = m_per_deg_lng(ILLUR[0])
        best, blat = 1e18, None
        for i in range(len(pts) - 1):
            dd = _closest_m([pts[i], pts[i + 1]], *ILLUR)
            if dd < best:
                best, blat = dd, (pts[i][0] + pts[i + 1][0]) / 2
        assert blat > ILLUR[0], "Illur doit être passée au NORD"
        assert d >= 45.0
        assert not any(v.get("name") == "Illur"
                       for v in (r.get("wrong_side_marks") or []))
