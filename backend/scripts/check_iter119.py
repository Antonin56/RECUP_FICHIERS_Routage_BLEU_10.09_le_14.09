"""Vérification locale iter119 — contraintes dures + découplage ZH.

1. Route Golfe → Vannes à ZH (tide 0) puis à +4 m : écart aux balises N°6 /
   No8 / Holavre, traversée de parcs/mouillages, temps de calcul.
2. Route Arradon → Île-aux-Moines (eau profonde, ZH) : sanité.
"""
import math
import sys
import time

sys.path.insert(0, "/app/backend")
from core.routing import compute_route, RouteError  # noqa: E402
from core.bathy import M_PER_DEG_LAT, m_per_deg_lng  # noqa: E402

MARKS = {
    "No6 (chenal Vannes)": (47.6281487, -2.7625103),
    "No8 (chenal Vannes)": (47.6294199, -2.7620161),
    "Holavre": (47.6082986, -2.8312696),
}


def min_dist(wps, pt):
    mlng = m_per_deg_lng(pt[0])
    best = float("inf")
    for i in range(len(wps) - 1):
        ax = (wps[i]["lng"] - pt[1]) * mlng
        ay = (wps[i]["lat"] - pt[0]) * M_PER_DEG_LAT
        bx = (wps[i + 1]["lng"] - pt[1]) * mlng
        by = (wps[i + 1]["lat"] - pt[0]) * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 <= 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / L2))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def run(name, start, end, tide):
    t0 = time.monotonic()
    try:
        res = compute_route(start[0], start[1], end[0], end[1], 1.0, 0.5, 10.0, tide)
    except RouteError as e:
        print(f"[{name}] tide={tide} -> RouteError {e.code}: {e.message[:90]} ({time.monotonic()-t0:.1f}s)")
        return None
    dt = time.monotonic() - t0
    off = (res.get("end_snapped") or {}).get("offset_m", 0)
    print(f"[{name}] tide={tide} OK dist={res['distance_m']/1000:.1f}km min_depth={res['min_depth_m']} "
          f"offset={off}m wp={len(res['waypoints'])} in {dt:.1f}s")
    for mn, pt in MARKS.items():
        d = min_dist(res["waypoints"], pt)
        if d < 2000:
            print(f"    écart {mn}: {d:.0f} m")
    for w in res.get("warnings", []):
        print(f"    ⚠ {w[:110]}")
    return res


START = (47.554, -2.905)       # entrée du Golfe
VANNES = (47.6553, -2.7594)    # port de Vannes
ARRADON = (47.610, -2.825)
MOINES = (47.595, -2.851)

run("Golfe→Vannes", START, VANNES, 0.0)
run("Golfe→Vannes", START, VANNES, 4.0)
run("Arradon→Moines", ARRADON, MOINES, 0.0)
