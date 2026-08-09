"""Diag 03/08 — Moteur C (signalmar.v3) sur le secteur d'Illur.

Vérifie les 4 règles armateur :
  1. géométrie IDENTIQUE dans les deux sens de parcours ;
  2. aucune latérale laissée du mauvais côté (ou avertissement explicite) ;
  3. marge latérale mesurée par tronçon ;
  4. jamais de « Passage impossible ».
"""
import math
import sys
import time

sys.path.insert(0, "/app/backend")

from core.routing_engines.algos import get_algo  # noqa: E402

# Aller/retour au travers du chenal d'Illur (est du Golfe du Morbihan).
A = (47.5720, -2.8300)   # côté large (sud-ouest du chenal)
B = (47.5905, -2.7850)   # côté terre (nord-est, vers Le Hézo / Noyalo)

CASES = [
    ("Illur A→B", A, B),
    ("Illur B→A", B, A),
]


def geom(res):
    return [(round(w["lat"], 6), round(w["lng"], 6)) for w in res["waypoints"]]


def main():
    algo = get_algo("signalmar.v3")
    out = {}
    for label, s, e in CASES:
        t0 = time.time()
        res = algo.compute_auto(s[0], s[1], e[0], e[1], 1.0, 0.5, 50.0, tide_m=0.0)
        dt = time.time() - t0
        g = geom(res)
        out[label] = g
        print(f"\n══ {label}  ({dt:.1f} s)")
        print(f"   points={len(g)}  distance={res.get('distance_m')} m  "
              f"fond mini={res.get('min_depth_m')} m  "
              f"marge utilisée={res.get('lateral_margin_used_m')} m")
        print(f"   sens: {res.get('engine_rules')}")
        print(f"   côtés corrigés: {res.get('side_fixed')}")
        print(f"   mauvais côté restant: {res.get('wrong_side_marks')}")
        print(f"   tronçons rouges: {res.get('compromised_legs')}")
        print(f"   motifs: {res.get('leg_reasons')}")
        lm = res.get("leg_margin_m") or []
        if lm:
            print(f"   marge mesurée: min={min(lm)} m  max={max(lm)} m")
        for w in (res.get("warnings") or [])[:5]:
            print(f"   ⚠ {w[:150]}")
    ga, gb = out["Illur A→B"], list(reversed(out["Illur B→A"]))
    same = ga == gb
    print(f"\n══ GÉOMÉTRIE IDENTIQUE DANS LES DEUX SENS : {same}")
    if not same:
        print(f"   {len(ga)} vs {len(gb)} points")
        for i, (p, q) in enumerate(zip(ga, gb)):
            if p != q:
                print(f"   1er écart au point {i}: {p} vs {q}")
                break


if __name__ == "__main__":
    main()
