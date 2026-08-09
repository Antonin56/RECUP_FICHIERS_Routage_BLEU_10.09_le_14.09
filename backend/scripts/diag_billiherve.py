"""Diagnostic 03/08/2026 — « Moteur C doit mieux respecter la balise vers
Billihervé » (Golfe du Morbihan, Île d'Arz → Pointe de Bilherve).

Mesure, pour la route de l'armateur (capture S-20260803-122825-W6P /
route R-20260803-122832-27), l'écart RÉEL du tracé à chaque balise proche,
et l'écart RECOMMANDÉ (standoff_circles). Compare Moteur A (v1), Moteur B
(v2 params par défaut) et une variante de paramètres (ce que pourrait être
le Moteur C si les paramètres étaient réglables depuis l'app).

Usage : cd /app/backend && python3 scripts/diag_billiherve.py
"""
import math
import sys
import time

sys.path.insert(0, "/app/backend")

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng  # noqa: E402
from core.routing_engines.algos.signalmar_v1 import core as v1  # noqa: E402
from core.routing_engines.algos.signalmar_v2 import SignalmarV2  # noqa: E402
from core.seamarks import get_seamarks  # noqa: E402

START = (47.531568, -2.915250)
END = (47.577466, -2.771563)
DRAFT, MARGIN, LATERAL, TIDE = 1.0, 0.5, 40.0, 0.0


def _seg_dist(p, a, b):
    mlng = m_per_deg_lng(p[0])
    ay, ax = (a[0] - p[0]) * M_PER_DEG_LAT, (a[1] - p[1]) * mlng
    by, bx = (b[0] - p[0]) * M_PER_DEG_LAT, (b[1] - p[1]) * mlng
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
    return math.hypot(ax + t * dx, ay + t * dy)


def closest(wps, mark):
    p = (mark["lat"], mark["lng"])
    return min(
        _seg_dist(p, (wps[i]["lat"], wps[i]["lng"]), (wps[i + 1]["lat"], wps[i + 1]["lng"]))
        for i in range(len(wps) - 1)
    )


def report(label, res, marks, circles):
    wps = res["waypoints"]
    print(f"\n── {label} : {res['distance_m'] / 1000:.2f} km, {len(wps)} points, "
          f"fond mini {res['min_depth_m']} m")
    rows = []
    for m in marks:
        d = closest(wps, m)
        if d > 250.0:
            continue
        reco = circles.get((round(m["lat"], 6), round(m["lng"], 6)))
        rows.append((d, m.get("name") or m.get("kind") or "?", m.get("kind"), reco))
    for d, name, kind, reco in sorted(rows)[:10]:
        flag = ""
        if reco and d < reco:
            flag = f"  ⚠ SOUS l'écart recommandé ({reco:.0f} m)"
        print(f"   {d:7.1f} m — {name} [{kind}] reco={reco if reco else '—'}{flag}")
    for w in res.get("warnings") or []:
        print(f"   ! {w[:120]}")


def main():
    sm = get_seamarks()
    lat_s, lat_n = min(START[0], END[0]) - 0.02, max(START[0], END[0]) + 0.02
    lng_w, lng_e = min(START[1], END[1]) - 0.02, max(START[1], END[1]) + 0.02
    marks = [m for m in sm.marks
             if lat_s <= m["lat"] <= lat_n and lng_w <= m["lng"] <= lng_e]
    circles = {(round(c[0], 6), round(c[1], 6)): c[2]
               for c in sm.standoff_circles(lat_s, lat_n, lng_w, lng_e)}
    print(f"{len(marks)} balises dans la fenêtre, {len(circles)} avec écart recommandé")

    t0 = time.monotonic()
    res_a = v1.compute_route(*START, *END, DRAFT, MARGIN, LATERAL, tide_m=TIDE)
    print(f"\n[Moteur A calculé en {time.monotonic() - t0:.1f} s]")
    report("Moteur A (signalmar.v1)", res_a, marks, circles)

    algo = SignalmarV2()
    t0 = time.monotonic()
    res_b = algo.compute_auto(*START, *END, DRAFT, MARGIN, LATERAL, TIDE, params={})
    print(f"\n[Moteur B calculé en {time.monotonic() - t0:.1f} s]")
    report("Moteur B (v2, params par défaut)", res_b, marks, circles)

    variant = {"standoff_pad_m": 40.0, "standoff_max_detour_m": 1200.0,
               "standoff_exempt_m": 120.0, "standoff_max_marks": 24}
    t0 = time.monotonic()
    res_c = algo.compute_auto(*START, *END, DRAFT, MARGIN, LATERAL, TIDE, params=variant)
    print(f"\n[Variante paramétrée calculée en {time.monotonic() - t0:.1f} s]")
    report(f"Variante {variant}", res_c, marks, circles)


if __name__ == "__main__":
    main()
