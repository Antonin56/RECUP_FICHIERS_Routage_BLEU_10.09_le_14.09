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


# ═════════════════════════════════════════════════════════════════════════
# BRANCHEMENT DISTANT (ordre armateur 04/09/2026) — serveur OVH.
#
# Le serveur de l'armateur publie un index v2 (schéma PLAT : nom de dalle →
# {bbox, valid_pct, …}, dalles alignées sur les multiples EXACTS de 0.1°,
# nommées tile_{lat_sw}_{lng_sw}.npy) protégé par ?token=… (403 sinon).
# Les dalles sont téléchargées À LA DEMANDE, persistées dans
# data/tiles/remote_cache/ puis servies en memmap (LRU) : une dalle n'est
# JAMAIS retéléchargée tant qu'elle est sur le disque.
# Si le serveur ne répond pas (index inaccessible), REPLI sur l'archive
# locale (TileBathy ci-dessus, dalles data/tiles/tandem_20m/).
# ⚠️ AUCUN moteur (A-I) ne consomme ce module — logique v8.1.0 intacte.
# ═════════════════════════════════════════════════════════════════════════

import os
import threading
import time

REMOTE_CACHE = Path(__file__).resolve().parent.parent / "data" / "tiles" / \
    "remote_cache"
_REMOTE_TIMEOUT_S = 10.0
_RETRY_COOLDOWN_S = 120.0     # re-tentative serveur / dalle en échec

LABEL_OVH = "Serveur OVH (v2.0)"
LABEL_ARCHIVE = "Archive (Repli)"


class RemoteTileBathy:
    """Lecteur des dalles OVH (index v2 plat) avec cache disque + memmap."""

    def __init__(self, base_url: str, token: str,
                 cache_dir: Path = REMOTE_CACHE) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.version = ""
        self.tile_deg = 0.1
        self.cell_deg = 0.0002
        self.nrows = self.ncols = 500
        self.tiles: dict[str, dict] = {}
        self._grids: dict[str, np.ndarray] = {}       # memmap LRU
        self._failed: dict[str, float] = {}           # fname → ts échec
        self._lock = threading.Lock()

    # ── HTTP ────────────────────────────────────────────────────────────
    def _get(self, path: str) -> bytes:
        import httpx
        r = httpx.get(f"{self.base_url}/{path}", params={"token": self.token},
                      timeout=_REMOTE_TIMEOUT_S, follow_redirects=True)
        r.raise_for_status()
        return r.content

    def load_index(self) -> bool:
        """Télécharge et parse l'index v2. False si serveur injoignable."""
        try:
            idx = json.loads(self._get("index.json"))
            self.version = str(idx.get("version", ""))
            self.tile_deg = float(idx.get("tile_deg", 0.1))
            self.cell_deg = float(idx.get("cell_deg", 0.0002))
            shape = idx.get("shape", [500, 500])
            self.nrows, self.ncols = int(shape[0]), int(shape[1])
            self.tiles = idx["tiles"]
            # Copie disque (diagnostic / reprise hors-ligne future).
            (self.cache_dir / "index.json").write_text(json.dumps(idx))
            return True
        except Exception:
            return False

    # ── Résolution point → dalle (multiples exacts de tile_deg) ─────────
    def _fname_for(self, lat: float, lng: float) -> Optional[str]:
        sw_lat = math.floor(lat / self.tile_deg) * self.tile_deg
        sw_lng = math.floor(lng / self.tile_deg) * self.tile_deg
        fname = f"tile_{sw_lat:.1f}_{sw_lng:.1f}.npy"
        return fname if fname in self.tiles else None

    def _grid(self, fname: str) -> Optional[np.ndarray]:
        with self._lock:
            if fname in self._grids:
                self._grids[fname] = self._grids.pop(fname)   # refresh LRU
                return self._grids[fname]
        path = self.cache_dir / fname
        if not path.exists():
            last_fail = self._failed.get(fname, 0.0)
            if time.time() - last_fail < _RETRY_COOLDOWN_S:
                return None
            try:
                data = self._get(fname)
                part = path.with_suffix(".part")
                part.write_bytes(data)
                os.replace(part, path)
            except Exception:
                self._failed[fname] = time.time()
                return None
        try:
            grid = np.load(path, mmap_mode="r")
        except Exception:                     # fichier corrompu → purge
            path.unlink(missing_ok=True)
            self._failed[fname] = time.time()
            return None
        with self._lock:
            if len(self._grids) >= _CACHE_MAX:
                self._grids.pop(next(iter(self._grids)))
            self._grids[fname] = grid
        return grid

    def depth_at(self, lat: float, lng: float) -> Optional[float]:
        fname = self._fname_for(lat, lng)
        if fname is None:
            return None
        grid = self._grid(fname)
        if grid is None:
            return None
        w, s, e, n = self.tiles[fname]["bbox"]
        r = int((n - lat) / self.cell_deg)
        c = int((lng - w) / self.cell_deg)
        if not (0 <= r < self.nrows and 0 <= c < self.ncols):
            return None
        v = float(grid[r, c])
        return None if math.isnan(v) else v

    def stats(self) -> dict:
        cached = sum(1 for f in self.cache_dir.glob("tile_*.npy"))
        return {"tiles_indexed": len(self.tiles), "tiles_cached": cached,
                "failed_recent": len(self._failed)}


class TileService:
    """Source de dalles unique : OVH d'abord, repli archive locale.

    Le repli est RÉÉVALUÉ toutes les _RETRY_COOLDOWN_S : si le serveur
    revient, la source rebascule sur OVH au prochain appel."""

    def __init__(self) -> None:
        self._remote: Optional[RemoteTileBathy] = None
        self._archive: Optional[TileBathy] = None
        self._source = ""                     # "ovh" | "archive"
        self._probed_at = 0.0
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        with self._lock:
            if self._source == "ovh":
                return
            if self._source == "archive" and \
                    time.time() - self._probed_at < _RETRY_COOLDOWN_S:
                return
            base = os.environ.get("TILE_SERVER_URL", "")
            token = os.environ.get("TILE_SERVER_TOKEN", "")
            self._probed_at = time.time()
            if base and token:
                remote = RemoteTileBathy(base, token)
                if remote.load_index():
                    self._remote, self._source = remote, "ovh"
                    return
            if self._archive is None and DEFAULT_INDEX.exists():
                self._archive = TileBathy()
            self._source = "archive"

    def depth_at(self, lat: float, lng: float) -> Optional[float]:
        self._ensure()
        if self._source == "ovh" and self._remote is not None:
            return self._remote.depth_at(lat, lng)
        return self._archive.depth_at(lat, lng) if self._archive else None

    def source_info(self) -> dict:
        self._ensure()
        if self._source == "ovh" and self._remote is not None:
            st = self._remote.stats()
            return {"source": "ovh", "label": LABEL_OVH,
                    "version": self._remote.version, **st}
        st = (self._archive.stats() if self._archive else {})
        indexed = sum(v.get("tiles_indexed", 0) for v in st.values())
        present = sum(v.get("tiles_present", 0) for v in st.values())
        return {"source": "archive", "label": LABEL_ARCHIVE, "version": "",
                "tiles_indexed": indexed, "tiles_cached": present}


_service: Optional[TileService] = None


def get_tile_service() -> TileService:
    global _service
    if _service is None:
        _service = TileService()
    return _service
