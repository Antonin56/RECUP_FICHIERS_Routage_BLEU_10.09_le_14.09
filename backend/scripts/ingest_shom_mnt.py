"""SignalMar — Ingestion du MNT SHOM (N1, 20/07/2026).

Convertit l'Arc/Info ASCII grid (.asc) du SHOM en grille binaire compacte :
  - bathy_morbihan.npy  : float32 (NROWS, NCOLS), NaN = pas de donnée.
                          Convention stockée = PROFONDEUR en m sous le zéro
                          hydrographique (positif vers le bas ; le fichier
                          SHOM « ZNEG » donne l'altitude, négative sous ZH).
  - bathy_morbihan.json : métadonnées {ncols, nrows, xll, yll, cellsize,
                          product, downloaded_at}.

Usage : python scripts/ingest_shom_mnt.py [--keep-sources]
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "bathy"
ASC = DATA_DIR / "MNT_COTIER_MORBIHAN_TANDEM_PBMA" / "DONNEES" / \
    "MNT_COTIER_MORBIHAN_TANDEM_20m_WGS84_PBMA_ZNEG.asc"
OUT_NPY = DATA_DIR / "bathy_morbihan.npy"
OUT_META = DATA_DIR / "bathy_morbihan.json"


def main() -> None:
    with rasterio.open(ASC) as src:
        z = src.read(1).astype(np.float32)
        nodata = src.nodata
        t = src.transform
        meta = {
            "product": "MNT_COTIER_MORBIHAN_TANDEM_20m_WGS84_PBMA_ZNEG",
            "license": "Licence Ouverte — Bathymétrie © SHOM (non officiel navigation)",
            "ncols": src.width,
            "nrows": src.height,
            # Coin haut-gauche + pas (grille lignes = nord → sud).
            "x0": t.c, "y0": t.f, "dx": t.a, "dy": t.e,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
    if nodata is not None:
        z[z == np.float32(nodata)] = np.nan
    # Garde-fou : le nodata SHOM est un float géant parfois arrondi.
    z[np.abs(z) > 1e30] = np.nan
    # ZNEG (altitude, négative sous ZH) → PROFONDEUR positive vers le bas.
    depth = -z
    np.save(OUT_NPY, depth)
    OUT_META.write_text(json.dumps(meta, indent=2))
    valid = np.isfinite(depth)
    print(f"grid {meta['nrows']}x{meta['ncols']}  valid={valid.mean():.1%}  "
          f"depth min={np.nanmin(depth):.1f} max={np.nanmax(depth):.1f} m")
    print(f"saved {OUT_NPY} ({OUT_NPY.stat().st_size/1e6:.0f} MB)")

    if "--keep-sources" not in sys.argv:
        import shutil
        for p in [DATA_DIR / "morbihan.7z", DATA_DIR / "MNT_COTIER_MORBIHAN_TANDEM_PBMA"]:
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
        print("sources cleaned")


if __name__ == "__main__":
    main()
