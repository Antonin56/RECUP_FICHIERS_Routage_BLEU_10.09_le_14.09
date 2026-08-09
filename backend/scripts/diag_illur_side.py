"""Diag 03/08/2026 — « la route ne respecte pas la balise tribord Illur ».

Mesure sur les ROUTES RÉELLES de l'armateur (documents computed_routes) :
  * distance mini du tracé à chaque balise proche ;
  * de quel CÔTÉ la balise se trouve par rapport au sens de progression ;
  * profondeur (ZH) au niveau de la balise et de part et d'autre du tracé.

Usage : cd /app/backend && python3 scripts/diag_illur_side.py [route_id …]
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
from core.seamarks import get_seamarks  # noqa: E402

DEFAULT_IDS = ["R-20260803-122832-27", "R-20260803-121610-37"]
WINDOW_M = 400.0


def _xy(p, ref_lat, ref_lng):
    mlng = m_per_deg_lng(ref_lat)
    return ((p[1] - ref_lng) * mlng, (p[0] - ref_lat) * M_PER_DEG_LAT)


def closest_seg(pts, mark):
    """(distance_m, index segment, t, côté) — côté : +1 = à BÂBORD du tracé,
    -1 = à TRIBORD (produit vectoriel du segment vers la balise)."""
    best = (float("inf"), -1, 0.0, 0)
    for i in range(len(pts) - 1):
        ax, ay = _xy(pts[i], mark[0], mark[1])
        bx, by = _xy(pts[i + 1], mark[0], mark[1])
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 <= 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / L2))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px, py)
        if d < best[0]:
            # Vecteur segment → balise (la balise est à l'origine).
            cross = dx * (0 - ay) - dy * (0 - ax)
            best = (d, i, t, 1 if cross > 0 else -1)
    return best


async def main():
    ids = sys.argv[1:] or DEFAULT_IDS
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ.get("DB_NAME", "signalmar")]
    sm = get_seamarks()
    grid = get_grid()

    for rid in ids:
        doc = await db.computed_routes.find_one({"route_id": rid})
        if not doc:
            print(f"\n### {rid} : introuvable")
            continue
        res = doc.get("result") or {}
        wps = [(w["lat"], w["lng"]) for w in res.get("waypoints") or []]
        print(f"\n### {rid} — moteur {doc.get('engine_id')} ({doc.get('engine_name')}), "
              f"{res.get('distance_m')} m, {len(wps)} points, "
              f"kind={doc.get('kind')}, fond mini {res.get('min_depth_m')} m")
        req = doc.get("request") or {}
        print(f"    demande : tirant {req.get('draft_m')} m, marge fond "
              f"{req.get('depth_margin_m')} m, marge latérale {req.get('lateral_margin_m')}, "
              f"marée {req.get('use_tide')}, sécurité +{req.get('safety_extra_m')}")
        if len(wps) < 2:
            continue
        lat_s = min(p[0] for p in wps) - 0.01
        lat_n = max(p[0] for p in wps) + 0.01
        lng_w = min(p[1] for p in wps) - 0.01
        lng_e = max(p[1] for p in wps) + 0.01
        circles = {(round(x[0], 6), round(x[1], 6)): x[2]
                   for x in sm.standoff_circles(lat_s, lat_n, lng_w, lng_e)}
        rows = []
        for m in sm.marks:
            if not (lat_s <= m["lat"] <= lat_n and lng_w <= m["lng"] <= lng_e):
                continue
            d, i, t, side = closest_seg(wps, (m["lat"], m["lng"]))
            if d > WINDOW_M:
                continue
            rows.append((d, m, i, t, side))
        for d, m, i, t, side in sorted(rows, key=lambda r: r[0])[:12]:
            reco = circles.get((round(m["lat"], 6), round(m["lng"], 6)))
            cat = m.get("category") or ""
            # Côté : la balise est à bâbord (+1) ou à tribord (-1) du tracé.
            side_txt = "à BÂBORD du tracé" if side > 0 else "à TRIBORD du tracé"
            verdict = ""
            if m.get("kind") == "lateral":
                # Balise tribord (verte) : le navire doit la laisser à
                # TRIBORD dans le sens conventionnel → la balise doit être
                # à tribord du tracé si l'on progresse dans ce sens.
                ok = (cat == "starboard" and side < 0) or (cat == "port" and side > 0)
                verdict = "  → côté CONFORME" if ok else "  → côté À VÉRIFIER"
            dep = grid.depth_at(m["lat"], m["lng"]) if grid else None
            print(f"  {d:7.1f} m — {m.get('name') or m.get('kind')} "
                  f"[{m.get('kind')}/{cat} {m.get('colour')}] reco={reco or '—'} "
                  f"segment #{i} t={t:.2f} {side_txt}{verdict} fond_balise={dep}")
        for w in res.get("warnings") or []:
            print(f"  ! {w[:140]}")


if __name__ == "__main__":
    asyncio.run(main())
