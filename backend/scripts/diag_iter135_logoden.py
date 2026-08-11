"""Rejoue le bloc de réparation autour de Logoden pour comprendre l'échec."""
from pathlib import Path
import math
import numpy as np
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import core.routing_engines.algos.signalmar_v1.core as v1
from core.routing_engines.algos.signalmar_v2.standoff import _closest_on
from core.seamarks import get_seamarks, SIDE_ABSOLUTE, ISOLATED_SIDE_BATHY

LOG = (47.6112008, -2.8303268)
mlng = 111320 * math.cos(math.radians(LOG[0]))

orig_rep = v1._repair_segments
grabbed = {}

def spy(grid, pts, *a, **k):
    if len(pts) > 15 and 'in' not in grabbed:
        din, _, _ = _closest_on(pts, *LOG, mlng)
        if din < 200:
            grabbed.update(dict(pts=list(pts), a=a, k=k, grid=grid))
    return orig_rep(grid, pts, *a, **k)

v1._repair_segments = spy
try:
    from core.routing_engines.algos.signalmar_v5 import SignalmarV5
    SignalmarV5().compute_auto(47.53214474552446, -2.92678544441799,
                               47.615738117406266, -2.8154603141514327,
                               1.5, 0.5, 10.0)
finally:
    v1._repair_segments = orig_rep

pts = grabbed['pts']
min_depth, lateral, clearance, strict_depth = grabbed['a']
ga = grabbed['k'].get('gates_arr')
ex = grabbed['k'].get('strict_exempt')
grid = grabbed['grid']

t1 = SIDE_ABSOLUTE.set(True); t2 = ISOLATED_SIDE_BATHY.set(True)
try:
    def safe(x, y):
        return v1._corridor_safe(grid, x, y, min_depth, lateral, clearance,
                                 half_m=15.0, gates_arr=ga, strict_depth_w=strict_depth)
    # reconstitue la boucle de _repair_segments jusqu'au bloc Logoden
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        a = out[-1]
        if safe(a, pts[i + 1]):
            out.append(pts[i + 1]); i += 1; continue
        j = i + 1
        while j < len(pts) - 1 and not safe(pts[j], pts[j + 1]):
            j += 1
        b = pts[j]
        d_log, _, _ = _closest_on([a, b], *LOG, mlng)
        print(f"bloc: a={a} b={b} d_log={d_log:.0f}")
        if d_log < 400:
            span_deg = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
            best_min = v1._centerline_min(grid, [a] + pts[i + 1:j + 1])
            print('  best_min original =', best_min)
            for pad in (0.008, 0.03, 0.08, 0.25):
                px = min(2400, max(700, int((span_deg + 2 * pad + 0.02) / 0.001) + 50))
                try:
                    leg = v1._solve_leg(grid, a, b, min_depth, lateral, max_px=px,
                                        pad_min=pad, do_round=False,
                                        strict_depth=strict_depth,
                                        strict_exempt=ex, pad_frac=0.05)["raw"]
                except Exception as e:
                    print(f'  pad={pad}: solve ECHEC {type(e).__name__} {e}')
                    continue
                leg2 = v1._repair_segments(grid, leg, min_depth, lateral, clearance,
                                           strict_depth, ex, 1, gates_arr=ga)
                cand = leg2 if i == 0 else ([a] + leg2 if abs(leg2[0][0]-a[0])+abs(leg2[0][1]-a[1]) > 1e-9 else [a] + leg2[1:])
                bad = [kk for kk in range(len(cand) - 1) if not safe(cand[kk], cand[kk + 1])]
                dl, _, pl = _closest_on(cand, *LOG, mlng)
                pen = v1._wrong_side_penalty_m(cand, ex)
                print(f'  pad={pad}: n={len(cand)} d_log={dl:.0f} north={pl[0]>LOG[0]} pen={pen:.1f} bad_segs={bad[:5]}')
                for q in cand:
                    print(f'    {q[0]:.6f},{q[1]:.6f}')
            break
        out.extend(pts[i + 1:j + 1])
        i = j
finally:
    ISOLATED_SIDE_BATHY.reset(t2); SIDE_ABSOLUTE.reset(t1)
