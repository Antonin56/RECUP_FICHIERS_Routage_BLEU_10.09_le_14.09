"""Balayage 03/08 — conformité du BALISAGE du Moteur C sur le Golfe du Morbihan.

Calcule N routes couvrant les chenaux du Golfe (Illur, Drenec, Creizic, La
Jument, Grand Mouton…) et liste TOUTES les balises laissées du mauvais côté —
latérales ROUGE/VERTE comme CARDINALES.

Usage : python scripts/diag_v3_sweep_morbihan.py [engine_c|engine_b]
"""
import sys
import time

sys.path.insert(0, "/app/backend")

from core.routing_engines.algos import get_algo  # noqa: E402
from core.routing_engines.algos.signalmar_v3.direction import grid_for, mid_mlng  # noqa: E402
from core.routing_engines.algos.signalmar_v3.side import audit_sides  # noqa: E402
from core.nav_rules import merge_params  # noqa: E402
from core.bathy import get_grid  # noqa: E402

# Points de repère du Golfe (mer → intérieur).
P = {
    "Port-Navalo": (47.5455, -2.9185),
    "Grand Mouton": (47.5600, -2.9080),
    "Arradon": (47.6165, -2.8230),
    "Conleau": (47.6265, -2.7830),
    "Ile aux Moines N": (47.6020, -2.8480),
    "Ile aux Moines S": (47.5760, -2.8480),
    "Creizic": (47.5800, -2.8760),
    "Ilur O": (47.5760, -2.8060),
    "Ilur E": (47.5870, -2.7820),
    "Le Hezo": (47.5940, -2.7830),
    "Ile d'Arz N": (47.6010, -2.7960),
    "Noyalo": (47.5880, -2.7570),
    "Larmor-Baden": (47.5860, -2.8960),
    "Bailleron": (47.5620, -2.7900),
    "Kerners": (47.5580, -2.8560),
}

PAIRS = [
    ("Port-Navalo", "Le Hezo"),
    ("Port-Navalo", "Ilur E"),
    ("Port-Navalo", "Noyalo"),
    ("Port-Navalo", "Conleau"),
    ("Port-Navalo", "Arradon"),
    ("Grand Mouton", "Ilur E"),
    ("Kerners", "Le Hezo"),
    ("Kerners", "Ilur E"),
    ("Ile aux Moines S", "Ilur E"),
    ("Ile aux Moines S", "Noyalo"),
    ("Creizic", "Ilur E"),
    ("Creizic", "Le Hezo"),
    ("Larmor-Baden", "Ilur E"),
    ("Larmor-Baden", "Noyalo"),
    ("Ilur O", "Le Hezo"),
    ("Bailleron", "Arradon"),
    ("Bailleron", "Conleau"),
    ("Ile d'Arz N", "Port-Navalo"),
    ("Noyalo", "Arradon"),
    ("Le Hezo", "Larmor-Baden"),
]


def main():
    engine = sys.argv[1] if len(sys.argv) > 1 else "engine_c"
    algo = get_algo("signalmar.v3" if engine == "engine_c" else "signalmar.v2")
    params = merge_params(None)
    total_viol = 0
    per_mark = {}
    for a_name, b_name in PAIRS:
        a, b = P[a_name], P[b_name]
        t0 = time.time()
        try:
            res = algo.compute_auto(a[0], a[1], b[0], b[1], 1.0, 0.5, 50.0, tide_m=0.0)
        except Exception as err:  # noqa: BLE001
            print(f"✗ {a_name} → {b_name} : ÉCHEC {type(err).__name__} {err}")
            continue
        wps = res.get("waypoints") or []
        pts = [(w["lat"], w["lng"]) for w in wps]
        if len(pts) < 2:
            print(f"✗ {a_name} → {b_name} : tracé vide")
            continue
        mlng = mid_mlng(pts)
        viol = audit_sides(pts, mlng=mlng, params=params, exempt=(a, b),
                           dir_grid=grid_for(a, b),
                           depth_gate=(get_grid(), 1.0 + 0.5 + 2.0))
        total_viol += len(viol)
        flag = "✓" if not viol else "✗"
        print(f"{flag} {a_name:16s} → {b_name:14s} {res['distance_m'] / 1000:5.1f} km "
              f"fond {res.get('min_depth_m')!s:>5} ({time.time() - t0:4.1f} s) "
              f"corrigées={res.get('side_fixed')}")
        for v in viol:
            per_mark[v["name"]] = per_mark.get(v["name"], 0) + 1
            print(f"      ⚠ {v['name']} ({v['kind']}/{v['category']}) doit être "
                  f"{v['side_required']} — passage à {v['dist_m']} m")
    print(f"\n══ TOTAL violations = {total_viol}")
    for k, n in sorted(per_mark.items(), key=lambda t: -t[1]):
        print(f"   {n:2d} × {k}")


if __name__ == "__main__":
    main()
