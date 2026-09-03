"""SignalMar — Lecteur de dalles bathymétriques PC (index.json + .npy memmap).

Lit les dalles produites par le script PC de l'armateur selon
memory/SPEC_DALLAGE_BATHY_PC.md (03/09/2026) :
  - dalles float32 (tile_size × tile_size), ligne 0 = bord NORD ;
  - convention : PROFONDEUR (m) sous le ZH, positive vers le bas,
    NaN = terre / île bakée / hors donnée = JAMAIS navigable ;
  - index.json : couches ordonnées de la plus FINE à la plus GROSSIÈRE,
    la plus fine qui couvre le point GAGNE, ses NaN ne sont JAMAIS
    rebouchés (même règle que core.bathy.MosaicGrid).

⚠️ PÉRIMÈTRE (ordre armateur 03/09) : module AUTONOME, testable seul
(tests/test_tile_reader.py). AUCUN moteur (A-I) ne l'utilise — le
branchement éventuel se fera sur GO explicite.

Particularités gérées :
  - dalles alignées sur la grille SHOM native → coins décalés d'une
    fraction de cellule vs les multiples exacts de tile_deg (ex.
    lng0 = -3.20003 pour ix = -33) : la résolution point → dalle teste la
    clé floor() PUIS les 8 voisines sur les bords ;
  - dalle référencée dans l'index mais fichier ABSENT du disque
    (livraison partielle) : ignorée proprement (aucune exception),
    comptée dans stats()["missing_files"].
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

import numpy as np

DEFAULT_INDEX = Path(__file__).resolve().parent.parent / "data" / "tiles" / \
    "tandem_20m" / "index.json"

_CACHE_MAX = 64          # memmaps ouverts simultanément (LRU simple)


class _TileLayer:
    """Une couche de l'index (ex. tandem_20m) : méta + accès memmap."""

    def __init__(self, index_dir: Path, spec: dict, tile_deg: float,
                 cell_deg: float, tile_size: int) -> None:
        self.name: str = spec["name"]
        self.product: str = spec.get("product", "")
        self.bounds: list[float] = spec.get("bounds", [])
        self.tile_deg = tile_deg
        self.cell_deg = cell_deg
        self.tile_size = tile_size
        # Les dalles vivent soit dans index_dir/<dir>, soit à plat à côté
        # de l'index (livraison test armateur 03/09).
        sub = index_dir / spec.get("dir", "")
        self.dir = sub if sub.is_dir() and sub != index_dir else index_dir
        self.tiles: dict[str, dict] = spec["tiles"]
        self._cache: dict[str, np.ndarray] = {}
        self.missing: set[str] = set()

    # ── Accès memmap (cache LRU) ────────────────────────────────────────
    def _grid(self, key: str) -> Optional[np.ndarray]:
        if key in self._cache:
            self._cache[key] = self._cache.pop(key)      # refresh LRU
            return self._cache[key]
        if key in self.missing:
            return None
        path = self.dir / self.tiles[key]["file"]
        if not path.exists():
            self.missing.add(key)
            return None
        grid = np.load(path, mmap_mode="r")
        if len(self._cache) >= _CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = grid
        return grid

    # ── Résolution point → dalle ────────────────────────────────────────
    def _tile_contains(self, key: str, lat: float, lng: float) -> bool:
        meta = self.tiles.get(key)
        if meta is None:
            return False
        span = self.tile_size * self.cell_deg
        lat0, lng0 = meta["lat0"], meta["lng0"]
        return (lat0 - span) < lat <= lat0 and lng0 <= lng < (lng0 + span)

    def _key_for(self, lat: float, lng: float) -> Optional[str]:
        iy = math.floor(lat / self.tile_deg)
        ix = math.floor(lng / self.tile_deg)
        key = f"{iy}_{ix}"
        if self._tile_contains(key, lat, lng):
            return key
        # Coins décalés d'une fraction de cellule → tester les voisines.
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == dx == 0:
                    continue
                k = f"{iy + dy}_{ix + dx}"
                if self._tile_contains(k, lat, lng):
                    return k
        return None

    def depth_at(self, lat: float, lng: float) -> tuple[bool, Optional[float]]:
        """(couvert, profondeur). couvert=True dès qu'une dalle LISIBLE
        contient le point — profondeur None si NaN (terre = interdit)."""
        key = self._key_for(lat, lng)
        if key is None:
            return False, None
        grid = self._grid(key)
        if grid is None:                      # fichier absent (livraison partielle)
            return False, None
        meta = self.tiles[key]
        r = int((meta["lat0"] - lat) / self.cell_deg)
        c = int((lng - meta["lng0"]) / self.cell_deg)
        if not (0 <= r < self.tile_size and 0 <= c < self.tile_size):
            return False, None
        v = float(grid[r, c])
        return True, (None if math.isnan(v) else v)

    def tiles_for_bbox(self, west: float, south: float, east: float,
                       north: float) -> list[str]:
        """Clés des dalles de l'index intersectant la bbox (arithmétique
        d'indices, pas de R-tree — spec §8)."""
        span = self.tile_size * self.cell_deg
        out = []
        for key, meta in self.tiles.items():
            lat0, lng0 = meta["lat0"], meta["lng0"]
            if lng0 < east and (lng0 + span) > west \
                    and (lat0 - span) < north and lat0 > south:
                out.append(key)
        return out


class TileBathy:
    """Lecteur multi-couches des dalles PC (API alignée sur MosaicGrid)."""

    def __init__(self, index_path: Path = DEFAULT_INDEX) -> None:
        idx = json.loads(Path(index_path).read_text())
        self.convention: str = idx["convention"]
        self.crs: str = idx.get("crs", "EPSG:4326")
        self.row_order: str = idx.get("row_order", "north_to_south")
        self.layers = [
            _TileLayer(Path(index_path).parent, spec, idx["tile_deg"],
                       idx["cell_deg"], idx["tile_size"])
            for spec in idx["layers"]
        ]

    def depth_at(self, lat: float, lng: float) -> Optional[float]:
        """Profondeur (m sous ZH) — la couche la plus FINE qui couvre le
        point gagne ; None si NaN (terre) ou hors couverture. Ses NaN ne
        sont jamais rebouchés par une couche plus grossière."""
        for layer in self.layers:
            covered, v = layer.depth_at(lat, lng)
            if covered:
                return v
        return None

    def tiles_for_bbox(self, west: float, south: float, east: float,
                       north: float) -> dict[str, list[str]]:
        return {l.name: l.tiles_for_bbox(west, south, east, north)
                for l in self.layers}

    def stats(self) -> dict:
        out = {}
        for layer in self.layers:
            present = sum(1 for m in layer.tiles.values()
                          if (layer.dir / m["file"]).exists())
            out[layer.name] = {
                "tiles_indexed": len(layer.tiles),
                "tiles_present": present,
                "missing_files": sorted(layer.missing),
                "bounds": layer.bounds,
            }
        return out
