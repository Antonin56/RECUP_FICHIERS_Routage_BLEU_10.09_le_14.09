"""Diag itér. 135 — reproduction anomalies armateur 11/08 (moteur E) :
1. Grand Mouton (verte 47.5619945,-2.9137521) pas respectée ;
2. No2 (rouge 47.5376391,-2.9124922) laissée du mauvais côté (~127 m) ;
3. embardée en zigzag à l'entrée du port du Crouesty."""
from pathlib import Path
import math
import sys

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from core.routing_engines.algos.signalmar_v5 import SignalmarV5
from core.routing_engines.algos.signalmar_v2.standoff import _closest_on

START = (47.57517422898507, -2.8806422077521003)
END = (47.54185598400968, -2.8990867189961116)
GRAND_MOUTON = (47.5619945, -2.9137521)   # verte (starboard)
NO2 = (47.5376391, -2.9124922)            # rouge (port)

TIDE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0

eng = SignalmarV5()
r = eng.compute_auto(START[0], START[1], END[0], END[1], 1.0, 0.5, 10.0, tide_m=TIDE)
pts = [(w["lat"], w["lng"]) for w in r["waypoints"]]
print(f"tide={TIDE}  n_wp={len(pts)}  dist={r.get('distance_m')}  risk={r.get('risk')}")
print("wrong_side:", [(v.get('name'), round(v.get('dist_m', 0))) for v in (r.get('wrong_side_marks') or [])])
print("end_snapped:", r.get("end_snapped"))
for name, (la, ln) in [("GrandMouton", GRAND_MOUTON), ("No2", NO2)]:
    mlng = 111_320.0 * math.cos(math.radians(la))
    d, i, p = _closest_on(pts, la, ln, mlng)
    # côté : vecteur balise->point projeté vs direction de progression
    a, b = pts[max(0, i)], pts[min(len(pts) - 1, i + 1)]
    de = (b[1] - a[1]) * mlng
    dn = (b[0] - a[0]) * 110_574.0
    n = math.hypot(de, dn) or 1.0
    de, dn = de / n, dn / n
    ve = (p[1] - ln) * mlng
    vn = (p[0] - la) * 110_574.0
    cross = de * vn - dn * ve  # >0 : balise à DROITE de la route (route passe à gauche)
    print(f"{name}: d={d:.0f} m  seg={i}  cross(balise vs route)={cross:.0f}"
          f"  (>0: route laisse la balise à TRIBORD)")
print("--- derniers 15 waypoints (entrée port) ---")
for w in pts[-15:]:
    print(f"  {w[0]:.6f},{w[1]:.6f}")
