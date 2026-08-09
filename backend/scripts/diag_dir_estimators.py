"""Diag 03/08 — estimateurs de direction conventionnelle près d'Illur.

Compare, pour chaque latérale isolée du secteur, la direction retenue
aujourd'hui (gradient « distance au large ») et une direction dérivée de
l'ALIGNEMENT des latérales du même côté (axe du chenal), orientée par le
gradient. Objectif : savoir si l'axe donnerait le bon côté interdit.
"""
import math
import sys

sys.path.insert(0, "/app/backend")

from core.seamarks import get_seamarks  # noqa: E402

NAMES = ("Illur", "Grand Mouton", "Les Tisserands", "Jument", "Billihervé", "Drenec")
AXIS_MAX_M = 3000.0  # on élargit volontairement pour voir les voisins utiles


def bearing(de, dn):
    return (math.degrees(math.atan2(de, dn)) + 360.0) % 360.0


def main():
    sm = get_seamarks()
    marks = {(m.get("name") or ""): m for m in sm.marks
             if (m.get("name") or "") in NAMES and m["lat"] > 47.5 and m["lng"] > -3.0}
    for name, m in marks.items():
        mlng = 111_320.0 * math.cos(math.radians(m["lat"]))
        grad = sm.conventional_dir(m["lat"], m["lng"])
        cur = sm._mark_dir(m)
        print(f"\n── {name} [{m.get('category')}] ({m['lat']:.6f},{m['lng']:.6f})")
        print(f"   gradient abri     : {bearing(*grad):6.1f}°" if grad else "   gradient : None")
        print(f"   direction retenue : {bearing(*cur):6.1f}°" if cur else "   retenue : None")
        # Voisins du MÊME côté (candidats pour l'axe du chenal).
        cands = []
        for o in sm.marks:
            if o is m or o.get("kind") != "lateral":
                continue
            if o.get("category") != m.get("category"):
                continue
            de_ = (o["lng"] - m["lng"]) * mlng
            dn_ = (o["lat"] - m["lat"]) * 110_574.0
            d = math.hypot(de_, dn_)
            if 10.0 < d <= AXIS_MAX_M:
                cands.append((d, o.get("name") or "?", bearing(de_, dn_)))
        for d, nm, br in sorted(cands)[:4]:
            print(f"     voisin même côté : {nm:16s} à {d:7.0f} m, cap {br:6.1f}°")
        # Voisin de côté OPPOSÉ (couple potentiel).
        opp = []
        other = "port" if m.get("category") == "starboard" else "starboard"
        for o in sm.marks:
            if o.get("kind") != "lateral" or o.get("category") != other:
                continue
            de_ = (o["lng"] - m["lng"]) * mlng
            dn_ = (o["lat"] - m["lat"]) * 110_574.0
            d = math.hypot(de_, dn_)
            if d <= AXIS_MAX_M:
                opp.append((d, o.get("name") or "?", bearing(de_, dn_)))
        for d, nm, br in sorted(opp)[:3]:
            print(f"     côté opposé      : {nm:16s} à {d:7.0f} m, cap {br:6.1f}°")


if __name__ == "__main__":
    main()
