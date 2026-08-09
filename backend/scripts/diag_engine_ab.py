"""Comparatif Moteur A (signalmar.v1) / Moteur B (signalmar.v2) — cas
« Fernais 25 » (capture armateur 02/08/2026 08:47, estuaire de la Loire).

Vérifie que le correctif « écart minimal aux balises » du Moteur B écarte le
tracé de la bouée SANS dégrader le fond mini ni allonger la route.
"""
import math
import sys
import time

sys.path.insert(0, "/app/backend")

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng  # noqa: E402
from core.routing_engines.algos import get_algo  # noqa: E402
from core.seamarks import get_seamarks  # noqa: E402

CASES = [
    # (nom, start, end, draft, marge_fond, marge_latérale)
    ("Loire → Golfe (capture, marge AUTO)",
     (47.30330604878526, -2.0971425094619605),
     (47.56115369856387, -2.8754832035414895), 1.0, 2.5, 10.0),
    ("Loire → Golfe (marge manuelle 50 m)",
     (47.30330604878526, -2.0971425094619605),
     (47.56115369856387, -2.8754832035414895), 1.0, 2.5, 50.0),
    ("Golfe : Arradon → sud (zone pilote, non-régression)",
     (47.610, -2.825), (47.545, -2.900), 1.5, 0.5, 10.0),
    ("Chenal de Vannes (contrainte dure, non-régression)",
     (47.610, -2.825), (47.6395, -2.7580), 1.0, 0.5, 10.0),
]


def seg_dist(m_lat, m_lng, a, b):
    mlng = m_per_deg_lng(m_lat)
    ay, ax = (a[0] - m_lat) * M_PER_DEG_LAT, (a[1] - m_lng) * mlng
    by, bx = (b[0] - m_lat) * M_PER_DEG_LAT, (b[1] - m_lng) * mlng
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
    return math.hypot(ax + t * dx, ay + t * dy)


def audit(res):
    """Balises frôlées : (nom, écart, écart recommandé)."""
    sm = get_seamarks()
    wps = [(w["lat"], w["lng"]) for w in res["waypoints"]]
    la = [w[0] for w in wps]
    lo = [w[1] for w in wps]
    out = []
    for (m_lat, m_lng, r_std, name) in sm.standoff_circles(
            min(la) - 0.005, max(la) + 0.005, min(lo) - 0.005, max(lo) + 0.005):
        d = min(seg_dist(m_lat, m_lng, wps[i], wps[i + 1])
                for i in range(len(wps) - 1))
        if d < r_std - 1.0:
            out.append((name or "?", round(d, 1), round(r_std)))
    return sorted(out, key=lambda t: t[1])


def main():
    a1 = get_algo("signalmar.v1")
    a2 = get_algo("signalmar.v2")
    for (name, s, e, draft, dm, lm) in CASES:
        print(f"\n=== {name} ===")
        for label, algo in (("A v1", a1), ("B v2", a2)):
            t0 = time.monotonic()
            try:
                res = algo.compute_auto(s[0], s[1], e[0], e[1], draft, dm, lm, 0.0)
            except Exception as exc:  # noqa: BLE001
                print(f"  {label}: ÉCHEC {exc}")
                continue
            viol = audit(res)
            print(f"  {label}: {res['distance_m']/1000:7.2f} km | "
                  f"mini {res['min_depth_m']} m | {len(res['waypoints']):3d} wp | "
                  f"{time.monotonic()-t0:4.1f} s | corrigées="
                  f"{res.get('standoff_fixed') or '-'}")
            print(f"        balises frôlées : {viol if viol else 'aucune'}")


if __name__ == "__main__":
    main()
