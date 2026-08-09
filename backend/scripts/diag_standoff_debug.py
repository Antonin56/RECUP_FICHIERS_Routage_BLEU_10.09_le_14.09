"""Debug séquentiel : raisons de refus des candidats d'écartement (Moteur B)."""
import math
import sys

sys.path.insert(0, "/app/backend")

import numpy as np  # noqa: E402

from core.bathy import M_PER_DEG_LAT, get_grid, m_per_deg_lng  # noqa: E402
from core.routing_engines.algos import get_algo  # noqa: E402
from core.routing_engines.algos.signalmar_v1 import core as v1  # noqa: E402
from core.routing_engines.algos.signalmar_v2 import standoff as so  # noqa: E402
from core.seamarks import MOORING_EXEMPT_M, get_seamarks  # noqa: E402

S = (47.30330604878526, -2.0971425094619605)
E = (47.56115369856387, -2.8754832035414895)
DRAFT, DM, LM = 1.0, 2.5, 50.0

res = get_algo("signalmar.v1").compute_auto(S[0], S[1], E[0], E[1], DRAFT, DM, LM, 0.0)
pts = [(w["lat"], w["lng"]) for w in res["waypoints"]]
la = [p[0] for p in pts]
lo = [p[1] for p in pts]
mlng = m_per_deg_lng((min(la) + max(la)) / 2)
grid = get_grid()
sm = get_seamarks()
min_depth = max(DRAFT + DM, -2.5)
strict = DRAFT + DM + 2.0
cl = sm.clearance_points(min(la) - 0.01, max(la) + 0.01, min(lo) - 0.01, max(lo) + 0.01, min_depth)
clearance = np.asarray(cl, dtype=np.float64) if cl else None
exempt = (S, E)
ga = [g for g in sm.gates(min(la) - 0.01, max(la) + 0.01, min(lo) - 0.01, max(lo) + 0.01)
      if not any(so._d_m((g[0], g[1]), q[0], q[1], mlng) < MOORING_EXEMPT_M for q in exempt)]
gates = np.asarray(ga, dtype=np.float64) if ga else None
ctx = so._Ctx(grid, min_depth, LM, clearance, gates, strict, mlng)

todo = []
for (m_lat, m_lng, r_std, name) in sm.standoff_circles(
        min(la) - 0.005, max(la) + 0.005, min(lo) - 0.005, max(lo) + 0.005):
    if any(so._d_m((m_lat, m_lng), q[0], q[1], mlng) < 200.0 for q in exempt):
        continue
    d, _i, _P = so._closest_on(pts, m_lat, m_lng, mlng)
    if d < r_std - 1.0:
        todo.append((d, m_lat, m_lng, r_std, name))
todo.sort(key=lambda t: t[0])
print("à corriger :", [(t[4], round(t[0], 1)) for t in todo])

cur = list(pts)
for (_d0, m_lat, m_lng, r_std, name) in todo:
    target = r_std + 10.0
    circles = so._near_circles(ctx.clearance, m_lat, m_lng, mlng)
    base = [p for k, p in enumerate(cur)
            if k in (0, len(cur) - 1) or so._d_m(p, m_lat, m_lng, mlng) >= target]
    d, i, P = so._closest_on(base, m_lat, m_lng, mlng)
    ex = (P[1] - m_lng) * mlng
    ey = (P[0] - m_lat) * M_PER_DEG_LAT
    n = math.hypot(ex, ey) or 1.0
    ux, uy = ex / n, ey / n
    print(f"\n« {name} » écart actuel {d:.1f} → cible {target:.0f} (segment {i}, "
          f"{len(circles) if circles is not None else 0} cercles voisins)")
    ok = False
    for extra in (0.0, 15.0, 40.0, 80.0):
        for ang in (0.0, 20.0, -20.0, 40.0, -40.0):
            ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            vx, vy = ux * ca - uy * sa, ux * sa + uy * ca
            r = target + extra
            q = (m_lat + (vy * r) / M_PER_DEG_LAT, m_lng + (vx * r) / mlng)
            cand = base[:i + 1] + [q] + base[i + 1:]
            d2, _, _ = so._closest_on(cand, m_lat, m_lng, mlng)
            det = so._length_m(cand, mlng) - so._length_m(cur, mlng)
            reasons = []
            if d2 < target - 2.0:
                reasons.append(f"écart {d2:.0f}<cible")
            if det > 600.0:
                reasons.append(f"détour {det:.0f}")
            if not ctx.point_ok(q):
                reasons.append(f"pt {grid.depth_at(*q)}")
            if not so._clearance_not_worse(cur, cand, circles, mlng):
                if circles is not None:
                    d_old = so._min_dists(cur, circles, mlng)
                    d_new = so._min_dists(cand, circles, mlng)
                    bad = np.where(~((d_new >= circles[:, 2])
                                     | (d_new >= np.minimum(d_old, circles[:, 2]) - 2.0)))[0]
                    reasons.append("clearance " + ", ".join(
                        f"r={circles[k, 2]:.0f} {d_old[k]:.0f}→{d_new[k]:.0f}" for k in bad[:3]))
            lo_i, hi_i = max(0, i - 1), min(len(cand) - 1, i + 3)
            segbad = [k for k in range(lo_i, hi_i) if not ctx.seg_ok(cand[k], cand[k + 1])]
            if segbad:
                reasons.append(f"segments {segbad}")
            if not reasons:
                print(f"   OK extra={extra:.0f} ang={ang:+.0f} → écart {d2:.0f} détour {det:+.0f}")
                cur = cand
                ok = True
                break
            print(f"   ✗ extra={extra:4.0f} ang={ang:+5.0f} : {' | '.join(reasons)}")
        if ok:
            break
