"""Analyse moteur : jusqu'où la route remonte-t-elle la Vilaine selon le seuil ?"""
import sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from core.routing import compute_route, RouteError

START = (47.61, -2.825)          # Arradon (fallback testeur)
DEST = (47.4969, -2.3846)        # destination armateur (Foireuse)

for min_depth, label in [
    (0.3, "seuil 0.3 m (= tirant 1.5 + marge 0.5 - marée 1.7)"),
    (0.5, "seuil 0.5 m"),
    (1.0, "seuil 1.0 m"),
    (2.0, "seuil 2.0 m (sans marée)"),
]:
    try:
        r = compute_route(
            START[0], START[1], DEST[0], DEST[1],
            draft_m=1.5, depth_margin_m=0.5, lateral_margin_m=50.0, tide_m=2.0 - min_depth,
        )
        wps = r["waypoints"]
        print(f"=== {label} → OK, {len(wps)} wp, dernier {wps[-1]}, dist {round(r['distance_m'])} m, min {r.get('min_depth_m')}")
        for w in r.get("warnings", []):
            print("   ⚠", w)
    except RouteError as e:
        print(f"=== {label} → {e.code}: {e.message[:120]}")
        pw = (e.payload or {}).get("partial_waypoints")
        if pw:
            print("   partial jusqu'à", pw[-1])
