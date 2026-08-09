"""Diag 03/08/2026 — pourquoi le tracé passe du MAUVAIS CÔTÉ d'Illur et du
Grand Mouton (balises tribord vertes) sans être bloqué par le moteur.

Affiche pour chaque balise : la direction conventionnelle retenue par le
moteur, la balise appariée (le cas échéant), la profondeur du mauvais côté,
le rayon d'interdit réellement appliqué, et de quel côté / à quelle distance
passe le tracé de l'armateur.
"""
import asyncio
import math
import os
import sys

sys.path.insert(0, "/app/backend")

from dotenv import load_dotenv  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

load_dotenv("/app/backend/.env")

from core.bathy import M_PER_DEG_LAT, get_grid, m_per_deg_lng  # noqa: E402
from core.seamarks import (  # noqa: E402
    R_LATERAL_M, R_MARK_STANDOFF_M, get_seamarks,
)

ROUTE_ID = "R-20260803-122832-27"
NAMES = ("Illur", "Grand Mouton", "Les Tisserands", "Jument", "Billihervé")


def closest_point(pts, mark):
    mlng = m_per_deg_lng(mark[0])
    best = (float("inf"), None, None)
    for i in range(len(pts) - 1):
        ax = (pts[i][1] - mark[1]) * mlng
        ay = (pts[i][0] - mark[0]) * M_PER_DEG_LAT
        bx = (pts[i + 1][1] - mark[1]) * mlng
        by = (pts[i + 1][0] - mark[0]) * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 <= 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / L2))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px, py)
        if d < best[0]:
            best = (d, (px, py), (dx, dy))
    return best


async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ.get("DB_NAME", "signalmar")]
    doc = await db.computed_routes.find_one({"route_id": ROUTE_ID})
    pts = [(w["lat"], w["lng"]) for w in (doc["result"]["waypoints"])]
    sm = get_seamarks()
    grid = get_grid()
    strict_depth = 1.0 + 0.5 + 2.0  # tirant + marge + 2 m (cf. moteur)
    print(f"route {ROUTE_ID} — {len(pts)} points ; R_LATERAL_M={R_LATERAL_M} m, "
          f"standoff={R_MARK_STANDOFF_M} m, strict_depth={strict_depth} m\n")

    for m in sm.marks:
        if (m.get("name") or "") not in NAMES:
            continue
        d, p, seg = closest_point(pts, (m["lat"], m["lng"]))
        if d > 500:
            continue
        dir_ = sm._mark_dir(m)
        pair = sm._pair_of(m)
        wrong_depth = sm._wrong_side_depth(m)
        strict = sm._lateral_strict(m, strict_depth)
        # Côté du point le plus proche par rapport à la direction conventionnelle
        cross = None
        wrong_side = None
        if dir_ is not None and p is not None:
            de, dn = dir_
            cross = de * p[1] - dn * p[0]   # >0 ⇔ à GAUCHE de D
            if m.get("category") == "starboard":
                wrong_side = cross < 0      # interdit = droite de D
            elif m.get("category") == "port":
                wrong_side = cross > 0
        print(f"── {m['name']} [{m.get('kind')}/{m.get('category')} {m.get('colour')}] "
              f"({m['lat']:.6f}, {m['lng']:.6f})")
        print(f"   direction conventionnelle retenue : {dir_}")
        print(f"   balise appariée : {(pair or {}).get('name')} "
              f"[{(pair or {}).get('category')}]")
        print(f"   fond à la balise : {grid.depth_at(m['lat'], m['lng'])} m | "
              f"fond du MAUVAIS côté : {wrong_depth} m → balisage strict ? {strict}")
        print(f"   tracé : {d:.1f} m de la balise, côté "
              f"{'INTERDIT (mauvais côté)' if wrong_side else 'autorisé'} "
              f"(cross={cross:.1f} m²)" if cross is not None else "   tracé : côté indéterminé")
        zone = R_LATERAL_M if not strict else 200.0
        print(f"   interdit appliqué de ce côté : {zone:.0f} m → "
              f"{'BLOQUÉ' if (wrong_side and d < zone) else 'PASSAGE AUTORISÉ par le moteur'}\n")


if __name__ == "__main__":
    asyncio.run(main())
