"""Diagnostic 02/08/2026 — route qui passe SUR la balise « Fernais 25 »
(estuaire de la Loire) en marge AUTO. Mesure l'écart réel du tracé à la
balise selon la marge latérale, et la maille de la grille sur zone."""
import math
import sys
import time

sys.path.insert(0, "/app/backend")

from core.bathy import ZONE_FILES, get_grid, get_zone_grid, m_per_deg_lng  # noqa: E402
from core.routing import compute_route  # noqa: E402
from core.seamarks import get_seamarks  # noqa: E402

B = (47.3017288, -2.1100982)          # Fernais 25 (verte, tribord)
START = (47.30330604878526, -2.0971425094619605)
END = (47.56115369856387, -2.8754832035414895)


def seg_dist(p, a, b):
    mlng = m_per_deg_lng(p[0])
    ay, ax = (a[0] - p[0]) * 110574.0, (a[1] - p[1]) * mlng
    by, bx = (b[0] - p[0]) * 110574.0, (b[1] - p[1]) * mlng
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
    return math.hypot(ax + t * dx, ay + t * dy)


def dist_to_mark(wps):
    return min(seg_dist(B, (wps[i]["lat"], wps[i]["lng"]),
                        (wps[i + 1]["lat"], wps[i + 1]["lng"]))
               for i in range(len(wps) - 1))


def main():
    print("── Grilles disponibles ─────────────────────────────")
    for name in ZONE_FILES:
        g = get_zone_grid(name)
        if g is None:
            print(f"  {name}: absente")
            continue
        cov = g.covers(*B)
        print(f"  {name}: maille ~{abs(g.dy) * 110574:.0f} m, couvre Fernais 25 ? {cov}")
    g = get_grid()
    print(f"  depth_at(Fernais 25) = {g.depth_at(*B)}")

    sm = get_seamarks()
    circles = sm.standoff_circles(B[0] - 0.002, B[0] + 0.002, B[1] - 0.002, B[1] + 0.002)
    print("── Écart minimal attendu (standoff_circles) ────────")
    for c in circles:
        print("   ", c)

    print("── Routes Loire → Golfe (start/end de la capture) ──")
    for margin in (10.0, 50.0, 100.0, 200.0):
        t0 = time.monotonic()
        try:
            res = compute_route(*START, *END, 1.0, 2.5, margin, tide_m=0.0)
        except Exception as exc:  # noqa: BLE001
            print(f"  marge {margin:5.0f} m → ÉCHEC {exc}")
            continue
        d = dist_to_mark(res["waypoints"])
        print(f"  marge {margin:5.0f} m → écart Fernais 25 = {d:6.1f} m | "
              f"{res['distance_m'] / 1000:.1f} km | {time.monotonic() - t0:.1f} s | "
              f"mini {res['min_depth_m']} m")


if __name__ == "__main__":
    main()
