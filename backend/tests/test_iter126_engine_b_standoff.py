"""SignalMar — Itér. 126 (02/08/2026) : Moteur B / algo ``signalmar.v2``.

Bug armateur du 02/08 (capture 08:47) : en marge AUTO, la route Loire → Golfe
passait à **4,7 m** de la bouée verte « Fernais 25 ». Cause : l'écart minimal
aux balises est sauté dès que la maille dépasse 45 m, or hors zone pilote la
bathy est l'ATL100 (maille réelle 75-110 m).

Ces tests verrouillent :
  * la NON-RÉGRESSION du Moteur A (signalmar.v1) — tracé inchangé ;
  * la correction effective du Moteur B (signalmar.v2) — écart ≥ 55 m ;
  * l'absence de dégradation (distance, fond mini) ;
  * l'égalité stricte A/B en zone pilote (le correctif n'y change rien).
"""
import math

import pytest

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
from core.routing_engines.algos import ALGO_REGISTRY, get_algo
from core.seamarks import get_seamarks

# Départ/arrivée EXACTS de la route incriminée (R-20260802-064254-JH).
START = (47.30330604878526, -2.0971425094619605)
END = (47.56115369856387, -2.8754832035414895)
FERNAIS_25 = (47.3017288, -2.1100982)


def _seg_dist(m_lat, m_lng, a, b):
    mlng = m_per_deg_lng(m_lat)
    ay, ax = (a[0] - m_lat) * M_PER_DEG_LAT, (a[1] - m_lng) * mlng
    by, bx = (b[0] - m_lat) * M_PER_DEG_LAT, (b[1] - m_lng) * mlng
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
    return math.hypot(ax + t * dx, ay + t * dy)


def _dist_to(res, mark):
    wps = [(w["lat"], w["lng"]) for w in res["waypoints"]]
    return min(_seg_dist(mark[0], mark[1], wps[i], wps[i + 1])
               for i in range(len(wps) - 1))


def _violations(res):
    """Balises dont l'écart recommandé n'est pas respecté."""
    sm = get_seamarks()
    wps = [(w["lat"], w["lng"]) for w in res["waypoints"]]
    la = [w[0] for w in wps]
    lo = [w[1] for w in wps]
    out = []
    for (m_lat, m_lng, r_std, name) in sm.standoff_circles(
            min(la) - 0.005, max(la) + 0.005, min(lo) - 0.005, max(lo) + 0.005):
        d = min(_seg_dist(m_lat, m_lng, wps[i], wps[i + 1])
                for i in range(len(wps) - 1))
        if d < r_std - 5.0:
            out.append((name, round(d, 1)))
    return out


def test_v2_registered_and_v1_untouched():
    assert "signalmar.v1" in ALGO_REGISTRY
    assert "signalmar.v2" in ALGO_REGISTRY
    assert get_algo("signalmar.v1").version.startswith("1.")
    assert get_algo("signalmar.v2").version.startswith("2.")


@pytest.mark.parametrize("lateral", [10.0, 50.0])
def test_engine_b_ecarte_la_balise_fernais_25(lateral):
    a = get_algo("signalmar.v1").compute_auto(
        START[0], START[1], END[0], END[1], 1.0, 2.5, lateral, 0.0)
    b = get_algo("signalmar.v2").compute_auto(
        START[0], START[1], END[0], END[1], 1.0, 2.5, lateral, 0.0)

    # A : le bug est bien reproduit (le tracé frôle la bouée).
    assert _dist_to(a, FERNAIS_25) < 40.0
    # B : écart respecté (60 m recommandés, tolérance de mesure).
    assert _dist_to(b, FERNAIS_25) >= 55.0
    # B : plus AUCUNE balise frôlée sur tout le trajet.
    assert _violations(b) == []
    # Aucune dégradation : route quasi identique, fond mini au moins égal.
    assert b["distance_m"] <= a["distance_m"] * 1.01
    assert b["min_depth_m"] >= a["min_depth_m"] - 0.01
    assert b.get("standoff_fixed")


def test_zone_pilote_identique_a_et_b():
    """Golfe du Morbihan (MNT 20 m) : l'écart minimal était déjà appliqué par
    le moteur → le correctif ne doit RIEN changer."""
    args = (47.610, -2.825, 47.6395, -2.7580, 1.0, 0.5, 10.0, 0.0)
    a = get_algo("signalmar.v1").compute_auto(*args)
    b = get_algo("signalmar.v2").compute_auto(*args)
    assert a["waypoints"] == b["waypoints"]
    assert a["distance_m"] == b["distance_m"]
    assert b.get("standoff_fixed") is None


def test_params_desactivation_du_correctif():
    """``standoff_enforce=False`` dans les params du moteur → B == A."""
    args = (START[0], START[1], END[0], END[1], 1.0, 2.5, 10.0, 0.0)
    a = get_algo("signalmar.v1").compute_auto(*args)
    b = get_algo("signalmar.v2").compute_auto(
        *args, params={"standoff_enforce": False})
    assert a["waypoints"] == b["waypoints"]


# ── Fragilité de la passe grossière (bathy agrégée 100 m) ─────────────────
# Cas mesuré le 02/08 : déplacer l'arrivée de 77 m fait passer le Moteur A de
# « Passage impossible » à une route de 84,4 km. Le Moteur B sectionne
# automatiquement au point de blocage annoncé.
FRAGILE_START = (47.302, -2.096)
FRAGILE_END = (47.5614, -2.87473)


def test_moteur_a_reproduit_la_fragilite():
    from core.routing import RouteError

    with pytest.raises(RouteError) as exc:
        get_algo("signalmar.v1").compute_auto(
            *FRAGILE_START, *FRAGILE_END, 1.0, 0.5, 10.0, 0.0)
    assert (exc.value.payload or {}).get("blocked_at")


def test_moteur_b_sectionne_et_trouve_la_route():
    b = get_algo("signalmar.v2").compute_auto(
        *FRAGILE_START, *FRAGILE_END, 1.0, 0.5, 10.0, 0.0)
    assert b["distance_m"] < 100_000  # ~84 km, pas de détour absurde
    assert b.get("split_via")
    assert any("2 tronçons" in w for w in b["warnings"])
    assert len(b["waypoints"]) >= 2
    # Le raccord se fait bien au voisinage du point de blocage annoncé.
    via = b["split_via"]
    wps = [(w["lat"], w["lng"]) for w in b["waypoints"]]
    dmin = min(
        math.hypot((p[0] - via["lat"]) * M_PER_DEG_LAT,
                   (p[1] - via["lng"]) * m_per_deg_lng(via["lat"]))
        for p in wps
    )
    assert dmin < 800.0
