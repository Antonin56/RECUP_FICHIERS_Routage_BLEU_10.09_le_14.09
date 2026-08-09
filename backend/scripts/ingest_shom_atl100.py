"""SignalMar — Ingestion du MNT façade Atlantique HOMONIM 100 m (22/07/2026,
extension de zone GO armateur).

Prépaquet SHOM public : MNT_FACADE_ATLANTIQUE_HOMONIM_PBMA.7z (464 Mo) →
MNT_ATL100m_HOMONIM_WGS84_PBMA_ZNEG.asc (~1 Go, 0.001° ≈ 100 m). On CROPPE à
la zone SignalMar France-Ouest (Manche Ouest → Pertuis charentais) et on
stocke la même convention que le Morbihan 20 m : PROFONDEUR (m) positive sous
le zéro hydrographique, NaN = pas de donnée / terre.

⚠️ Après ingestion : lancer ``ingest_islands.py --zone atl100`` (masque îles
OSM + auto-vérification) puis pytest tests/test_island_land_mask.py AVANT
toute livraison — même processus pour toute future zone.

Usage : python scripts/ingest_shom_atl100.py [--keep-sources]
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "bathy"
ASC = DATA_DIR / "dl" / "MNT_FACADE_ATLANTIQUE_HOMONIM_PBMA" / "DONNEES" / \
    "MNT_ATL100m_HOMONIM_WGS84_PBMA_ZNEG.asc"
OUT_NPY = DATA_DIR / "bathy_atl100.npy"
OUT_META = DATA_DIR / "bathy_atl100.json"

# Zone SignalMar France-Ouest (capture armateur 23/07 : Lannion/Saint-Malo →
# La Rochelle) — clipée à l'emprise du produit.
CROP_W, CROP_S, CROP_E, CROP_N = -5.45, 45.70, -1.00, 49.00


def main() -> None:
    with rasterio.open(ASC) as src:
        pw, ps, pe, pn = src.bounds
        w, s = max(CROP_W, pw), max(CROP_S, ps)
        e, n = min(CROP_E, pe), min(CROP_N, pn)
        print(f"produit bounds={src.bounds} → crop=({w},{s},{e},{n})")
        win = from_bounds(w, s, e, n, transform=src.transform)
        win = win.round_offsets().round_lengths()
        z = src.read(1, window=win).astype(np.float32)
        t = src.window_transform(win)
        nodata = src.nodata
        meta = {
            "product": "MNT_ATL100m_HOMONIM_WGS84_PBMA_ZNEG (crop France-Ouest)",
            "license": "Licence Ouverte — Bathymétrie © SHOM (non officiel navigation)",
            "ncols": z.shape[1],
            "nrows": z.shape[0],
            "x0": t.c, "y0": t.f, "dx": t.a, "dy": t.e,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
    if nodata is not None:
        z[z == np.float32(nodata)] = np.nan
    z[np.abs(z) > 1e30] = np.nan
    depth = -z  # ZNEG (altitude, négative sous ZH) → PROFONDEUR positive
    np.save(OUT_NPY, depth)
    OUT_META.write_text(json.dumps(meta, indent=2))
    valid = np.isfinite(depth)
    print(f"grid {meta['nrows']}x{meta['ncols']}  valid={valid.mean():.1%}  "
          f"depth min={np.nanmin(depth):.1f} max={np.nanmax(depth):.1f} m")
    print(f"saved {OUT_NPY} ({OUT_NPY.stat().st_size / 1e6:.0f} MB)")

    if "--keep-sources" not in sys.argv:
        dl = DATA_DIR / "dl"
        if dl.exists():
            shutil.rmtree(dl)
        print("sources cleaned (data/bathy/dl)")


if __name__ == "__main__":
    main()
