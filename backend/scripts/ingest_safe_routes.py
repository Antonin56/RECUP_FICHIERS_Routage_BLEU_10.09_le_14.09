"""SignalMar — Ingestion des ROUTES OFFICIELLES SÛRES OSM (26/08/2026).

Ways seamark « pointillés » des cartes marines :
  - recommended_track : route recommandée (le tracé conseillé lui-même) ;
  - navigation_line   : ALIGNEMENT (ligne de visée vers un amer — déborde la
                        partie navigable, à écrêter à l'usage) ;
  - fairway           : polygone de chenal (zone draguée/balisée) ;
  - two-way_route     : route à double sens.

Sortie : data/bathy/safe_routes.json
  {generated_at, bbox, count, features: [{id, kind, name, orientation,
   closed, coords: [[lat, lng], …], tags}]}

La donnée est ingérée sur TOUTE l'emprise ATL100 (réutilisable telle quelle
pour d'autres zones), via les utilitaires Overpass partagés (cache disque,
miroirs, backoff). AUCUN moteur ne la consomme encore : préparation du
Moteur H (en attente du GO armateur).

Usage : python scripts/ingest_safe_routes.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from overpass import fetch as overpass_fetch, tiles as overpass_tiles  # noqa: E402

DATA = ROOT / "data" / "bathy"
OUT = DATA / "safe_routes.json"

TYPES = "recommended_track|navigation_line|fairway|two-way_route"


def main() -> None:
    meta = json.loads((DATA / "bathy_atl100.json").read_text())
    S = meta["y0"] + meta["dy"] * meta["nrows"]
    N, Wb = meta["y0"], meta["x0"]
    Eb = meta["x0"] + meta["dx"] * meta["ncols"]

    tls = overpass_tiles(S, Wb, N, Eb)
    print(f"bbox=({S:.2f},{Wb:.2f},{N:.2f},{Eb:.2f}) — {len(tls)} tuile(s)",
          flush=True)
    seen: set[int] = set()
    feats: list[dict] = []
    for i, (s, w, n, e) in enumerate(tls):
        q = (f'[out:json][timeout:120];way["seamark:type"~"{TYPES}"]'
             f"({s},{w},{n},{e});out tags geom qt;")
        els = overpass_fetch(q, f"safe_routes_{i}")
        fresh = 0
        for el in els:
            if el["id"] in seen or not el.get("geometry"):
                continue
            seen.add(el["id"])
            t = el.get("tags", {})
            coords = [[round(g["lat"], 6), round(g["lon"], 6)]
                      for g in el["geometry"]]
            feats.append({
                "id": el["id"],
                "kind": t.get("seamark:type", ""),
                "name": t.get("seamark:name") or t.get("name") or "",
                "orientation": t.get("seamark:recommended_track:orientation")
                or t.get("seamark:navigation_line:orientation") or "",
                "closed": coords[0] == coords[-1] and len(coords) > 3,
                "coords": coords,
                "tags": {k: v for k, v in t.items() if k.startswith("seamark:")},
            })
            fresh += 1
        print(f"  tuile {i + 1}/{len(tls)} : {len(els)} ways ({fresh} nouveaux)",
              flush=True)

    from collections import Counter
    kinds = Counter(f["kind"] for f in feats)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bbox": [S, Wb, N, Eb],
        "count": len(feats),
        "kinds": dict(kinds),
        "features": feats,
    }, ensure_ascii=False))
    print(f"OK {OUT.name} : {len(feats)} ways {dict(kinds)}", flush=True)


if __name__ == "__main__":
    main()
