"""SignalMar — Ingestion des BOUÉES DE MOUILLAGE OSM (26/07/2026, demande armateur).

Récupère via Overpass toutes les bouées/postes de mouillage de la zone
(seamark:type=mooring) et les stocke en JSON local (data/bathy/moorings.json).
Le moteur de route les traite en ZONES INTERDITES (disque autour de chaque
bouée), sauf si le départ/l'arrivée est dans le champ de mouillage ou s'il
n'existe AUCUN autre passage (retry avec avertissement).

Usage : python scripts/ingest_moorings.py [--zone atl100|morbihan]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from overpass import fetch as overpass_fetch, tiles as overpass_tiles  # noqa: E402

DATA = ROOT / "data" / "bathy"
OUT = DATA / "moorings.json"
ZONES = {"morbihan": "bathy_morbihan.json", "atl100": "bathy_atl100.json"}


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
            f'[out:json][timeout:120];node["seamark:type"="mooring"]'
            f"({s},{w},{n},{e});out body qt;"
        )
        got = overpass_fetch(query, f"moorings_{args.zone}_{i}")
        fresh = [el for el in got if el["id"] not in seen]
        seen.update(el["id"] for el in got)
        elements.extend(fresh)
        print(f"  tuile {i + 1}/{len(tiles)} : {len(got)} mouillages ({len(fresh)} nouveaux)", flush=True)

    moorings = []
    for e in elements:
        t = e.get("tags", {})
        moorings.append({
            "id": e["id"],
            "lat": e["lat"],
            "lng": e["lon"],
            "category": t.get("seamark:mooring:category", ""),
            "name": t.get("seamark:name") or t.get("name") or "",
        })

    OUT.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "bbox": {"south": S, "west": W, "north": N, "east": E},
        "source": "OpenStreetMap/OpenSeaMap (ODbL)",
        "moorings": moorings,
    }, ensure_ascii=False))
    print("total:", len(moorings), "→", OUT)


if __name__ == "__main__":
    main()
