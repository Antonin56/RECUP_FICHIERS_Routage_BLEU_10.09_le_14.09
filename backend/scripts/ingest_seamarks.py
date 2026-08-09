"""SignalMar — Ingestion du balisage OSM/OpenSeaMap (v2, 22/07/2026).

Récupère via Overpass toutes les balises de la zone (latérales, cardinales,
dangers isolés, marques spéciales, eaux saines) et les stocke en JSON local
(data/bathy/seamarks.json) pour que le moteur de route n'ait JAMAIS de
dépendance réseau à l'exécution.

v2 (extension façade Atlantique) :
- emprise dérivée des MÉTADONNÉES de la grille cible (--zone atl100 par
  défaut = toute la façade) — aucune coordonnée codée en dur ;
- tuiles + cache disque + backoff 429 via scripts/overpass.py (incident
  « 429 façade Atlantique » du 22/07).

Usage : python scripts/ingest_seamarks.py [--zone atl100|morbihan]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from overpass import fetch as overpass_fetch, tiles as overpass_tiles  # noqa: E402

DATA = ROOT / "data" / "bathy"
OUT = DATA / "seamarks.json"
ZONES = {"morbihan": "bathy_morbihan.json", "atl100": "bathy_atl100.json"}
TYPES = (
    "buoy_lateral|beacon_lateral|buoy_cardinal|beacon_cardinal|"
    "buoy_isolated_danger|beacon_isolated_danger|buoy_special_purpose|"
    "beacon_special_purpose|buoy_safe_water|beacon_safe_water"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone", default="atl100", choices=sorted(ZONES))
    args = ap.parse_args()
    meta = json.loads((DATA / ZONES[args.zone]).read_text())
    S = meta["y0"] + meta["dy"] * meta["nrows"]
    N, W = meta["y0"], meta["x0"]
    E = meta["x0"] + meta["dx"] * meta["ncols"]

    tiles = overpass_tiles(S, W, N, E)
    print(f"zone={args.zone} bbox=({S:.3f},{W:.3f},{N:.3f},{E:.3f}) — {len(tiles)} tuile(s)", flush=True)
    seen: set[int] = set()
    elements: list[dict] = []
    for i, (s, w, n, e) in enumerate(tiles):
        query = (
            f'[out:json][timeout:120];node["seamark:type"~"{TYPES}"]'
            f"({s},{w},{n},{e});out body qt;"
        )
        got = overpass_fetch(query, f"seamarks_{args.zone}_{i}")
        fresh = [el for el in got if el["id"] not in seen]
        seen.update(el["id"] for el in got)
        elements.extend(fresh)
        print(f"  tuile {i + 1}/{len(tiles)} : {len(got)} balises ({len(fresh)} nouvelles)", flush=True)

    marks = []
    for e in elements:
        t = e.get("tags", {})
        stype = t.get("seamark:type", "")
        kind = (
            "lateral" if "lateral" in stype
            else "cardinal" if "cardinal" in stype
            else "isolated_danger" if "isolated_danger" in stype
            else "special" if "special_purpose" in stype
            else "safe_water"
        )
        category = t.get(f"seamark:{stype}:category", "")
        colour = t.get(f"seamark:{stype}:colour", "")
        # Latérale sans catégorie → déduite de la COULEUR (règle armateur :
        # jamais traiter une latérale en danger isolé).
        if kind == "lateral" and category not in ("port", "starboard"):
            if "green" in colour:
                category = "starboard"
            elif "red" in colour:
                category = "port"
        marks.append({
            "id": e["id"],
            "lat": e["lat"],
            "lng": e["lon"],
            "kind": kind,
            "type": stype,
            "category": category,          # port/starboard | north/south/east/west
            "colour": colour,
            "name": t.get("seamark:name") or t.get("name") or "",
            "light": t.get("seamark:light:character", ""),
        })

    OUT.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "bbox": {"south": S, "west": W, "north": N, "east": E},
        "source": "OpenStreetMap/OpenSeaMap (ODbL)",
        "marks": marks,
    }, ensure_ascii=False))

    print("total:", len(marks), dict(Counter(m["kind"] for m in marks)))
    lat_nocat = [m for m in marks if m["kind"] == "lateral" and m["category"] not in ("port", "starboard")]
    print("latérales sans côté après déduction couleur:", len(lat_nocat))
    print("saved:", OUT)


if __name__ == "__main__":
    main()
