"""Diag itér. 136 — route R-20260813-144317-MX (Arradon → La Trinité, moteur E).

Problèmes armateur (captures 13/08) :
1. « Truie d'Arradon » (rouge, isolée) recoupée à ~165 m du mauvais côté
   (warning présent mais tracé non corrigé) ;
2. arrivée La Trinité : trajectoire en Z + balises du chenal non respectées
   (N°12 mauvais côté, passage à ~1 m de N°4).

Usage : python scripts/diag_trinite_truie.py [engine_algo=signalmar.v6]
"""
import json
import math
import sys

sys.path.insert(0, "/app/backend")

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng  # noqa: E402
from core.routing_engines.algos import get_algo  # noqa: E402
from core.seamarks import get_seamarks  # noqa: E402

ALGO = sys.argv[1] if len(sys.argv) > 1 else "signalmar.v6"

START = (47.61270864146456, -2.8246830304036523)
END = (47.583795787592805, -3.0213006511557983)
DRAFT, DM, LM, TIDE = 1.0, 0.5, 30.0, 0.0

NAMES = ["Truie d'Arradon", "N°2", "Grassus", "N°4", "N°6", "N°8",
         "N°10", "Dalh", "N°5", "N°12", "N°7", "N°9"]


def closest_on(pts, lat, lng, mlng):
    best, bi, bp = 1e18, -1, None
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        ax, ay = (a[1] - lng) * mlng, (a[0] - lat) * M_PER_DEG_LAT
        bx, by = (b[1] - lng) * mlng, (b[0] - lat) * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px, py)
        if d < best:
            best, bi, bp = d, i, (lat + py / M_PER_DEG_LAT, lng + px / mlng)
    return best, bi, bp


def side_of(sm, m, p, mlng):
    """+1 = bon côté (navigable requis), −1 = mauvais, None = pas de signal."""
    d = sm.mark_dir_confident(m)
    if d is None:
        return None
    de, dn = d
    u = (dn, -de) if m["category"] == "port" else (-dn, de)
    ve = (p[1] - m["lng"]) * mlng
    vn = (p[0] - m["lat"]) * M_PER_DEG_LAT
    return 1 if ve * u[0] + vn * u[1] > 0 else -1


def main():
    algo = get_algo(ALGO)
    res = algo.compute_auto(START[0], START[1], END[0], END[1],
                            DRAFT, DM, LM, tide_m=TIDE)
    wps = res["waypoints"]
    pts = [(w["lat"], w["lng"]) for w in wps]
    print(f"=== {ALGO} — {res['distance_m']:.0f} m, {len(wps)} wps, "
          f"min_depth {res.get('min_depth_m')}, risk={res.get('risk')}")
    print("end_snapped:", res.get("end_snapped"))
    print("wrong_side :", res.get("wrong_side_marks"))
    for w in res.get("warnings", []):
        print("  warn:", w[:130])
    # distance dernier point ↔ arrivée demandée
    mlng = m_per_deg_lng(END[0])
    dend = math.hypot((pts[-1][0] - END[0]) * M_PER_DEG_LAT,
                      (pts[-1][1] - END[1]) * mlng)
    print(f"dernier wp ↔ arrivée demandée : {dend:.0f} m")

    sm = get_seamarks()
    print("\n--- balises nominatives (dist tracé / côté) ---")
    for name in NAMES:
        cands = [m for m in sm.marks if (m.get("name") == name
                 and 47.54 <= m["lat"] <= 47.63 and -3.05 <= m["lng"] <= -2.80)]
        for m in cands:
            ml = m_per_deg_lng(m["lat"])
            d, i, p = closest_on(pts, m["lat"], m["lng"], ml)
            s = side_of(sm, m, p, ml)
            lab = {1: "BON", -1: "MAUVAIS", None: "n/a"}[s]
            print(f"  {name:16s} {m['category']:9s} dist={d:6.1f} m  "
                  f"côté={lab}  (leg {i})")

    # détection de Z : angle entre segments consécutifs > 90° (repli)
    print("\n--- replis (angle > 100°) ---")
    for i in range(1, len(pts) - 1):
        ml = m_per_deg_lng(pts[i][0])
        v1 = ((pts[i][1] - pts[i-1][1]) * ml, (pts[i][0] - pts[i-1][0]) * M_PER_DEG_LAT)
        v2 = ((pts[i+1][1] - pts[i][1]) * ml, (pts[i+1][0] - pts[i][0]) * M_PER_DEG_LAT)
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 < 1 or n2 < 1:
            continue
        cos = (v1[0]*v2[0] + v1[1]*v2[1]) / (n1 * n2)
        ang = math.degrees(math.acos(max(-1, min(1, cos))))
        if ang > 100:
            print(f"  wp{i} {pts[i]}  virage {ang:.0f}°  (seg {n1:.0f} m → {n2:.0f} m)")

    json.dump(res, open(f"/tmp/diag_{ALGO.replace('.','_')}.json", "w"))
    print("\nrésultat → /tmp/diag_%s.json" % ALGO.replace('.', '_'))


if __name__ == "__main__":
    main()
