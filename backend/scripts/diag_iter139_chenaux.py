"""Diag itér. 139 — pourquoi les balises de chenal ne sont pas imposées ?

Routes armateur du 25/08 (engine_f) :
- R-20260825-130006-T8 : entrée du port de Lorient (bâbords du chenal recoupées)
- R-20260825-094137-TN : Belle-Île → Arradon (Kerpenhir recoupée, écarts Grand Mouton)
- R-20260825-115148-WJ : Le Croisic (Les Rouzins recoupée)
"""
import asyncio
import math
import os
import sys

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from core.bathy import M_PER_DEG_LAT, m_per_deg_lng  # noqa: E402
from core.seamarks import (  # noqa: E402
    ISOLATED_SIDE_BATHY, SIDE_ABSOLUTE, SIDE_ABSOLUTE_V6, get_seamarks,
)

ROUTES = ["R-20260825-130006-T8", "R-20260825-094137-TN", "R-20260825-115148-WJ"]


def closest(pts, lat, lng, mlng):
    best, bp = 1e18, None
    for i in range(len(pts) - 1):
        ax = (pts[i][1] - lng) * mlng
        ay = (pts[i][0] - lat) * M_PER_DEG_LAT
        bx = (pts[i + 1][1] - lng) * mlng
        by = (pts[i + 1][0] - lat) * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        d = math.hypot(ax + t * dx, ay + t * dy)
        if d < best:
            best, bp = d, (ax + t * dx, ay + t * dy)
    return best, bp


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "signalmar")]
    sm = get_seamarks()
    toks = [ISOLATED_SIDE_BATHY.set(True), SIDE_ABSOLUTE.set(True),
            SIDE_ABSOLUTE_V6.set(True)]
    for rid in ROUTES:
        doc = await db.computed_routes.find_one({"route_id": rid}, {"_id": 0})
        if not doc:
            print(rid, "ABSENT")
            continue
        res = doc["result"]
        pts = [(w["lat"], w["lng"]) for w in res["waypoints"]]
        req = doc.get("request") or {}
        print(f"\n===== {rid} ({doc.get('engine_id')}) dist "
              f"{res.get('distance_m'):.0f} m — wrong_side: "
              f"{[v.get('name') for v in (res.get('wrong_side_marks') or [])]}")
        # toutes les LATÉRALES à < 300 m du tracé : état complet
        lat_s = min(p[0] for p in pts) - 0.01
        lat_n = max(p[0] for p in pts) + 0.01
        lng_w = min(p[1] for p in pts) - 0.01
        lng_e = max(p[1] for p in pts) + 0.01
        mlng = m_per_deg_lng((lat_s + lat_n) / 2)
        for m in sm.marks:
            if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
                continue
            if not (lat_s <= m["lat"] <= lat_n and lng_w <= m["lng"] <= lng_e):
                continue
            d, bp = closest(pts, m["lat"], m["lng"], mlng)
            if d > 300:
                continue
            conf = sm.mark_dir_confident(m)
            pair = sm._pair_of(m)
            gap = None
            if pair is not None:
                gap = math.hypot((pair["lat"] - m["lat"]) * M_PER_DEG_LAT,
                                 (pair["lng"] - m["lng"]) * m_per_deg_lng(m["lat"]))
            side = "?"
            if conf is not None:
                de, dn = conf
                u = (dn, -de) if m["category"] == "port" else (-dn, de)
                side = "BON" if (bp[0] * u[0] + bp[1] * u[1]) > 0 else "MAUVAIS"
            infl = None
            if conf is not None:
                infl = 200.0 if gap is None else min(200.0, max(0.8 * gap, 40.0))
            print(f"  {str(m.get('name'))[:22]:22s} {m['category']:9s} "
                  f"d={d:5.0f}  côté={side:8s} conf={'oui' if conf else 'NON'} "
                  f"pair={'%.0f m' % gap if gap else 'non'} "
                  f"infl={infl if infl is None else round(infl)} "
                  f"navside={'oui' if sm.navigable_side(m) else 'non'}")
    for t in reversed(toks):
        pass


asyncio.run(main())
