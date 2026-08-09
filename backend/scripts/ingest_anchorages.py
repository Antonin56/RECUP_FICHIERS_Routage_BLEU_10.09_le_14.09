"""SignalMar — Ingestion des ZONES DE MOUILLAGE SURFACIQUES (27/07/2026).

Vidéo armateur 15h45 : la route traversait les champs de mouillage de
Barrarach / Île d'Arz (zones surfaciques OSM, différentes des bouées déjà
ingérées par ingest_moorings.py). Récupère via Overpass les zones
seamark:type=anchorage et anchor_berth (nœuds/chemins/relations) →
data/bathy/anchorages.json. Le moteur les traite comme les bouées de
mouillage : interdites, exemption < 400 m du départ/arrivée, ouvertes en
dernier recours (MOORINGS_OPEN) avec avertissement.

Usage : python scripts/ingest_anchorages.py [--zone morbihan|atl100]
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
OUT = DATA / "anchorages.json"
ZONES = {"morbihan": "bathy_morbihan.json", "atl100": "bathy_atl100.json"}


def _ring(el: dict) -> list[list[float]] | None:
    geom = el.get("geometry")
    if not geom or len(geom) < 3:
        return None
    return [[round(p["lat"], 6), round(p["lon"], 6)] for p in geom]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone", default="morbihan", choices=sorted(ZONES))
    args = ap.parse_args()
    meta = json.loads((DATA / ZONES[args.zone]).read_text())
    S = meta["y0"] + meta["dy"] * meta["nrows"]
    N, W = meta["y0"], meta["x0"]
    E = meta["x0"] + meta["dx"] * meta["ncols"]

    tiles = overpass_tiles(S, W, N, E)
    print(f"zone={args.zone} bbox=({S:.3f},{W:.3f},{N:.3f},{E:.3f}) — {len(tiles)} tuile(s)", flush=True)
    seen: set[tuple[str, int]] = set()
    zones: list[dict] = []
    for i, (s, w, n, e) in enumerate(tiles):
        query = (
            f"[out:json][timeout:180];("
            f'nwr["seamark:type"="anchorage"]({s},{w},{n},{e});'
            f'nwr["seamark:type"="anchor_berth"]({s},{w},{n},{e});'
            f");out geom qt;"
        )
        got = overpass_fetch(query, f"anchorages_{args.zone}_{i}")
        added = 0
        for el in got:
            key = (el["type"], el["id"])
            if key in seen:
                continue
            seen.add(key)
            name = (el.get("tags") or {}).get("name", "")
            if el["type"] == "node":
                zones.append({"id": el["id"], "name": name,
                              "lat": round(el["lat"], 6), "lng": round(el["lon"], 6)})
                added += 1
            elif el["type"] == "way":
                ring = _ring(el)
                if ring:
                    zones.append({"id": el["id"], "name": name, "poly": ring})
                    added += 1
            else:
                for mb in el.get("members", []):
                    if mb.get("role") not in ("outer", "") or mb.get("type") != "way":
                        continue
                    ring = _ring(mb)
                    if ring:
                        zones.append({"id": el["id"], "name": name, "poly": ring})
                        added += 1
        print(f"  tuile {i + 1}/{len(tiles)} : {len(got)} éléments ({added} retenus)", flush=True)

    n_poly = sum(1 for z in zones if "poly" in z)
    OUT.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "zone": args.zone,
        "anchorages": zones,
    }))
    print(f"OK — {len(zones)} zones ({n_poly} polygones, {len(zones) - n_poly} points) → {OUT}", flush=True)


if __name__ == "__main__":
    main()
