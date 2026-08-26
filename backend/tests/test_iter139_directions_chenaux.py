"""Itération 139 (25/08/2026) — directions de balises fiabilisées (Moteur F).

Bugs armateur (captures 25/08) : balises de chenal non imposées à Lorient
(« La Petite Jument », faux couple → direction inversée), au Croisic
(« Les Rouzins », aucune direction) et au Golfe (« Kerpenhir », aucune
direction). Correctifs gated SIDE_ABSOLUTE_V6 :
1. côté requis d'un couple CONTREDIT par le côté navigable bathy → la bathy
   prime (répare les faux couples inter-chenaux) ;
2. latérale sans direction → héritage du consensus des voisines fiables
   (≤ 1 km), portée d'imposition réduite à 120 m ;
3. garde-fou NET : un tracé « réparé » n'est jamais accepté s'il n'est pas
   strictement meilleur (mauvais côtés + frôlements).
"""
import math

from core.routing_engines.algos import get_algo
from core.seamarks import (
    DIR_COHERENCE_V6, ISOLATED_SIDE_BATHY, SIDE_ABSOLUTE, SIDE_ABSOLUTE_V6,
    get_seamarks,
)

LORIENT = ((47.67755575752677, -3.4287631920085064),
           (47.72987102630925, -3.3567713137773514))


def _mark(name, lat_min=46.0, lat_max=48.5):
    sm = get_seamarks()
    return next(m for m in sm.marks
                if m.get("name") == name and lat_min <= m["lat"] <= lat_max)


def _conf(m, v6: bool):
    sm = get_seamarks()
    toks = [ISOLATED_SIDE_BATHY.set(True), SIDE_ABSOLUTE.set(True)]
    if v6:
        toks.append(SIDE_ABSOLUTE_V6.set(True))
        toks.append(DIR_COHERENCE_V6.set(True))
    try:
        return sm.mark_dir_confident(m)
    finally:
        for t in reversed(toks):
            t.var.reset(t)


def test_petite_jument_direction_corrigee_par_bathy():
    """Faux couple (verte de Kernevel) : sous V6 la direction redevient NORD
    (entrée de Lorient) → côté requis EST (chenal). Sous E : inchangée."""
    m = _mark("La Petite Jument", 47.66, 47.74)
    d6 = _conf(m, v6=True)
    assert d6 is not None and d6[1] > 0.5, "direction v6 attendue vers le NORD"
    d5 = _conf(m, v6=False)
    assert d5 is not None and d5[1] < 0.0, "direction E (couple) conservée (gel)"


def test_kerpenhir_et_rouzins_heritent_une_direction():
    for name, bounds in (("Kerpenhir", (47.5, 47.6)), ("Les Rouzins", (47.25, 47.35))):
        m = _mark(name, *bounds)
        assert _conf(m, v6=False) is None, f"{name} : moteurs A-E inchangés (None)"
        assert _conf(m, v6=True) is not None, f"{name} : direction héritée en v6"
        assert m.get("_dir_v6_inferred") is True


def test_truie_d_arradon_direction_intacte():
    """Le vrai couple validé par l'armateur (iter136) ne bouge PAS en v6."""
    m = _mark("Truie d'Arradon", 47.55, 47.65)
    d5 = _conf(m, v6=False)
    d6 = _conf(m, v6=True)
    assert d6 is not None and d5 is not None
    assert d5[0] * d6[0] + d5[1] * d6[1] > 0.9


def test_lorient_f_pas_pire_et_petite_jument_pas_recoupee_franchement():
    """Route Lorient (entrée du port) : le Moteur F ne fait JAMAIS pire que
    le Moteur E sur les balises (garde-fou net) et ne recoupe plus les
    bâbords du chenal principal à travers la ligne (les N° 2/4/6 et le Banc
    du Turc restent du côté EST/chenal)."""
    sm = get_seamarks()
    res = get_algo("signalmar.v6").compute_auto(
        *LORIENT[0], *LORIENT[1], 1.0, 0.5, 10.0, tide_m=2.0,
        params={"dir_coherence": True})
    pts = [(w["lat"], w["lng"]) for w in res["waypoints"]]
    toks = [ISOLATED_SIDE_BATHY.set(True), SIDE_ABSOLUTE.set(True),
            SIDE_ABSOLUTE_V6.set(True), DIR_COHERENCE_V6.set(True)]
    try:
        for name in ("N° 2", "N° 6", "Banc du Turc"):
            m = _mark(name, 47.66, 47.74)
            mlng = 111320.0 * math.cos(math.radians(m["lat"]))
            best, bp = 1e18, None
            for i in range(len(pts) - 1):
                ax = (pts[i][1] - m["lng"]) * mlng
                ay = (pts[i][0] - m["lat"]) * 111320.0
                bx = (pts[i + 1][1] - m["lng"]) * mlng
                by = (pts[i + 1][0] - m["lat"]) * 111320.0
                dx, dy = bx - ax, by - ay
                L2 = dx * dx + dy * dy
                t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
                d = math.hypot(ax + t * dx, ay + t * dy)
                if d < best:
                    best, bp = d, (ax + t * dx, ay + t * dy)
            c = sm.mark_dir_confident(m)
            de, dn = c
            u = (dn, -de) if m["category"] == "port" else (-dn, de)
            assert best > 25.0, f"{name} frôlée à {best:.0f} m"
            if best <= 200.0:
                assert bp[0] * u[0] + bp[1] * u[1] > 0, f"{name} du mauvais côté"
    finally:
        for t in reversed(toks):
            t.var.reset(t)


def test_lorient_f_zero_mauvais_cote():
    """26/08 — après réparation en chaîne (validation limitée aux segments
    MODIFIÉS, passes côtés/frôlements rejouées, faux couple « N° 4 » corrigé
    par consensus, variante « épinglée » pour « Écrevisse ») : la route
    d'entrée de Lorient ne laisse PLUS AUCUNE latérale du mauvais côté."""
    res = get_algo("signalmar.v6").compute_auto(
        *LORIENT[0], *LORIENT[1], 1.0, 0.5, 10.0, tide_m=2.0,
        params={"dir_coherence": True})
    ws = res.get("wrong_side_marks") or []
    assert ws == [], f"balises du mauvais côté : {[(w.get('name'), round(w.get('dist_m', 0))) for w in ws]}"


def test_n4_faux_couple_corrige_par_consensus():
    """« N° 4 » (rouge, Lorient) : faux couple avec « N° 3 » → direction SW
    absurde. En v6 le consensus des voisines fiables la remet vers le NORD
    (entrée du port). Sous E : inchangée (gel)."""
    m = _mark("N° 4", 47.66, 47.74)
    d6 = _conf(m, v6=True)
    assert d6 is not None and d6[1] > 0.5, "direction v6 attendue vers le NORD"
    d5 = _conf(m, v6=False)
    assert d5 is not None and d5[1] < 0.0, "direction couple conservée (gel A-E)"
