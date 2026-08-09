"""SignalMar — Ingestion des DANGERS OSM/OpenSeaMap (v2, 22/07/2026).

Roches (couvrantes/découvrantes/à fleur d'eau/submergées), ÉPAVES et
OBSTRUCTIONS de la zone → data/bathy/hazards.json. Le moteur de route les
évite (zone d'exclusion) et l'app les rend CLIQUABLES.

Règle armateur (GO 22/07) : épaves bloquées UNIQUEMENT si dangereuses ou
profondeur inconnue — le tri fin (profondeur vs tirant d'eau) est fait à
l'exécution dans core/seamarks.py.

v2 (extension façade Atlantique) : emprise dérivée des métadonnées de la
grille cible + tuiles/cache/backoff via scripts/overpass.py.

Usage : python scripts/ingest_hazards.py [--zone atl100|morbihan]
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
OUT = DATA / "hazards.json"
ZONES = {"morbihan": "bathy_morbihan.json", "atl100": "bathy_atl100.json"}
TYPES = "rock|wreck|obstruction"


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
    seen: set[tuple[str, int]] = set()
    elements: list[dict] = []
    for i, (s, w, n, e) in enumerate(tiles):
        query = (
            f'[out:json][timeout:120];('
            f'node["seamark:type"~"^({TYPES})$"]({s},{w},{n},{e});'
            f'way["seamark:type"~"^({TYPES})$"]({s},{w},{n},{e});'
            f');out center body qt;'
        )
        got = overpass_fetch(query, f"hazards_{args.zone}_{i}")
        fresh = [el for el in got if (el["type"], el["id"]) not in seen]
        seen.update((el["type"], el["id"]) for el in got)
        elements.extend(fresh)
        print(f"  tuile {i + 1}/{len(tiles)} : {len(got)} dangers ({len(fresh)} nouveaux)", flush=True)

    hazards = []
    for e in elements:
        t = e.get("tags", {})
        stype = t.get("seamark:type", "")
        if stype not in ("rock", "wreck", "obstruction"):
            continue
        # Les ways (zones rocheuses…) sont réduits à leur CENTRE.
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lng = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None or lng is None:
            continue
        depth_raw = t.get(f"seamark:{stype}:depth", t.get("depth", ""))
        try:
            depth = float(str(depth_raw).replace(",", "."))
        except ValueError:
            depth = None
        hazards.append({
            "id": e["id"],
            "lat": lat,
            "lng": lng,
            "kind": stype,                                     # rock | wreck | obstruction
            "type": stype,
            "category": t.get(f"seamark:{stype}:category", ""),  # wreck: dangerous/non-dangerous/…
            "water_level": t.get(f"seamark:{stype}:water_level", ""),
            "depth_m": depth,
            "colour": "",
            "name": t.get("seamark:name") or t.get("name") or "",
            "light": "",
        })

    OUT.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "bbox": {"south": S, "west": W, "north": N, "east": E},
        "source": "OpenStreetMap/OpenSeaMap (ODbL)",
        "hazards": hazards,
    }, ensure_ascii=False))

    print("total:", len(hazards), dict(Counter(h["kind"] for h in hazards)))
    wl = Counter(h["water_level"] for h in hazards if h["kind"] == "rock")
    print("rock water_level:", dict(wl))
    wc = Counter(h["category"] for h in hazards if h["kind"] == "wreck")
    print("wreck category:", dict(wc))
    print("saved:", OUT)


if __name__ == "__main__":
    main()
