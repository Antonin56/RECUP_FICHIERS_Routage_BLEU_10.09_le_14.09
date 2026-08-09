"""SignalMar — Accès aux grilles bathymétriques SHOM (N1 20/07/2026,
multi-zones 22/07/2026).

Grilles produites par ``scripts/ingest_shom_mnt.py`` (Morbihan 20 m) et
``scripts/ingest_shom_atl100.py`` (façade Atlantique 100 m, crop France-Ouest) :
profondeurs (m, positives vers le bas) sous le ZÉRO HYDROGRAPHIQUE (PBMA ≈
plus basses mers) — calcul volontairement CONSERVATEUR. NaN = terre / île OSM
« bakée » / hors couverture produit → JAMAIS navigable.

MULTI-ZONES (extension GO armateur 22/07) : ``get_grid()`` renvoie une
``MosaicGrid`` empilant les grilles de ``ZONE_FILES`` (la plus FINE d'abord).
Règle de lecture : la grille la plus fine qui COUVRE le point gagne — ses NaN
ne sont JAMAIS rebouchés par une grille grossière (le 100 m lisse les côtes,
reboucher rouvrirait des îlots). Toute NOUVELLE zone = ajouter le couple
(npy, json) ici + ingest_islands.py --zone … + tests/test_island_land_mask.py.

Données : Licence Ouverte, Bathymétrie © SHOM, non utilisable pour la
navigation officielle.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional, Union

import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "bathy"

# Ordre = de la plus FINE à la plus GROSSIÈRE (résolution).
ZONE_FILES: list[tuple[str, str, str]] = [
    ("morbihan", "bathy_morbihan.npy", "bathy_morbihan.json"),
    ("atl100", "bathy_atl100.npy", "bathy_atl100.json"),
]

# Compat : chemins historiques de la zone pilote (scripts/tests existants).
NPY = DATA_DIR / "bathy_morbihan.npy"
META = DATA_DIR / "bathy_morbihan.json"

# Mètres par degré (approx. locales, suffisant à ces latitudes).
M_PER_DEG_LAT = 110_574.0


def m_per_deg_lng(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


class BathyGrid:
    """Lecture memmap d'UNE grille (jamais chargée entière en RAM)."""

    def __init__(self, meta_path: Path = META, npy_path: Path = NPY, name: str = "") -> None:
        meta = json.loads(meta_path.read_text())
        self.name = name
        self.ncols: int = meta["ncols"]
        self.nrows: int = meta["nrows"]
        self.x0: float = meta["x0"]          # lng du bord OUEST
        self.y0: float = meta["y0"]          # lat du bord NORD
        self.dx: float = meta["dx"]          # > 0
        self.dy: float = meta["dy"]          # < 0 (lignes nord → sud)
        self.product: str = meta["product"]
        self.grid = np.load(npy_path, mmap_mode="r")

    # ── Géoréférencement ────────────────────────────────────────────────
    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(west, south, east, north)"""
        return (
            self.x0,
            self.y0 + self.dy * self.nrows,
            self.x0 + self.dx * self.ncols,
            self.y0,
        )

    def covers(self, lat: float, lng: float) -> bool:
        w, s, e, n = self.bounds
        return s <= lat <= n and w <= lng <= e

    def contains_bbox(self, west: float, south: float, east: float, north: float) -> bool:
        w, s, e, n = self.bounds
        return w <= west and e >= east and s <= south and n >= north

    def rc(self, lat: float, lng: float) -> tuple[int, int]:
        col = int((lng - self.x0) / self.dx)
        row = int((lat - self.y0) / self.dy)
        return row, col

    def latlng(self, row: float, col: float) -> tuple[float, float]:
        return (
            self.y0 + (row + 0.5) * self.dy,
            self.x0 + (col + 0.5) * self.dx,
        )

    def depth_at(self, lat: float, lng: float) -> Optional[float]:
        """Profondeur (m sous ZH) à la cellule la plus proche, None si
        hors grille ou sans donnée."""
        if not self.covers(lat, lng):
            return None
        row, col = self.rc(lat, lng)
        if not (0 <= row < self.nrows and 0 <= col < self.ncols):
            return None
        v = float(self.grid[row, col])
        return None if math.isnan(v) else v

    def sample(self, lats: np.ndarray, lngs: np.ndarray) -> np.ndarray:
        """Profondeurs pleine résolution aux points donnés (vectorisé).
        NaN = hors grille / terre / pas de donnée."""
        rows = ((lats - self.y0) / self.dy).astype(np.int64)
        cols = ((lngs - self.x0) / self.dx).astype(np.int64)
        ok = (rows >= 0) & (rows < self.nrows) & (cols >= 0) & (cols < self.ncols)
        out = np.full(np.shape(lats), np.nan, dtype=np.float32)
        if ok.any():
            out[ok] = self.grid[rows[ok], cols[ok]]
        return out

    # ── Fenêtres décimées ───────────────────────────────────────────────
    def window(
        self, west: float, south: float, east: float, north: float, max_px: int = 400,
        pool: bool = False,
    ) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray, int]]:
        """Retourne (depth[ny,nx], lngs[nx], lats[ny], step) pour la bbox,
        décimée pour que max(ny,nx) ≤ max_px. None si aucune intersection.

        pool=True (22/07/2026, moteur de route) : décimation par MAX-POOLING
        (profondeur max de chaque bloc step×step) au lieu d'un simple
        sous-échantillonnage — un chenal étroit mais profond SURVIT à la
        décimation (bug « aucune route » Belle-Île → Golfe). La sécurité
        finale reste garantie par la passe fine + le profil pleine résolution."""
        w, s, e, n = self.bounds
        west, east = max(west, w), min(east, e)
        south, north = max(south, s), min(north, n)
        if west >= east or south >= north:
            return None
        r0, c0 = self.rc(north, west)   # coin haut-gauche
        r1, c1 = self.rc(south, east)   # coin bas-droit
        r0, c0 = max(r0, 0), max(c0, 0)
        r1, c1 = min(r1 + 1, self.nrows), min(c1 + 1, self.ncols)
        if r1 <= r0 or c1 <= c0:
            return None
        step = max(1, math.ceil(max(r1 - r0, c1 - c0) / max_px))
        if pool and step > 1:
            full = np.asarray(self.grid[r0:r1, c0:c1], dtype=np.float32)
            ny = (full.shape[0] // step) * step
            nx = (full.shape[1] // step) * step
            if ny == 0 or nx == 0:
                return None
            blocks = full[:ny, :nx].reshape(ny // step, step, nx // step, step)
            import warnings as _warnings
            with _warnings.catch_warnings():
                _warnings.simplefilter("ignore", RuntimeWarning)
                sub = np.nanmax(blocks, axis=(1, 3))
            rows = np.arange(r0, r0 + ny, step)
            cols = np.arange(c0, c0 + nx, step)
        else:
            sub = np.asarray(self.grid[r0:r1:step, c0:c1:step], dtype=np.float32)
            rows = np.arange(r0, r1, step)
            cols = np.arange(c0, c1, step)
        lats = self.y0 + (rows + 0.5) * self.dy
        lngs = self.x0 + (cols + 0.5) * self.dx
        return sub, lngs, lats, step


class MosaicGrid:
    """Empilement de grilles, la plus FINE d'abord (22/07/2026).

    Règles :
      - depth_at / sample : la PREMIÈRE grille qui couvre le point répond —
        ses NaN (terre, île « bakée », hors produit) ne sont JAMAIS rebouchés
        par une grille plus grossière (sécurité côtière).
      - window : déléguée à la première grille qui CONTIENT toute la bbox
        (→ comportement zone pilote inchangé), sinon à la plus grossière
        (qui englobe tout) — le raffinement par tronçon du moteur re-résout
        ensuite chaque tronçon dans la grille fine quand il y tient.
    """

    def __init__(self, grids: list[BathyGrid]) -> None:
        assert grids
        self.grids = grids
        self.dx = grids[0].dx
        self.dy = grids[0].dy
        self.product = " + ".join(g.product for g in grids)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        ws, ss, es, ns = zip(*(g.bounds for g in self.grids))
        return min(ws), min(ss), max(es), max(ns)

    def covers(self, lat: float, lng: float) -> bool:
        return any(g.covers(lat, lng) for g in self.grids)

    def depth_at(self, lat: float, lng: float) -> Optional[float]:
        for g in self.grids:
            if g.covers(lat, lng):
                return g.depth_at(lat, lng)
        return None

    def sample(self, lats: np.ndarray, lngs: np.ndarray) -> np.ndarray:
        out = np.full(np.shape(lats), np.nan, dtype=np.float32)
        remaining = np.ones(np.shape(lats), dtype=bool)
        for g in self.grids:
            w, s, e, n = g.bounds
            sel = remaining & (lats >= s) & (lats <= n) & (lngs >= w) & (lngs <= e)
            if sel.any():
                out[sel] = g.sample(lats[sel], lngs[sel])
                remaining &= ~sel
        return out

    def window(
        self, west: float, south: float, east: float, north: float, max_px: int = 400,
        pool: bool = False,
    ):
        for g in self.grids:
            if g.contains_bbox(west, south, east, north):
                return g.window(west, south, east, north, max_px=max_px, pool=pool)
        # Fenêtre COMBINÉE (23/07) : base = grille la plus grossière, puis
        # SUPERPOSITION des grilles fines là où leur emprise couvre le point —
        # la fine gagne TOUJOURS (même NaN = terre/île bakée). Indispensable :
        # l'ATL 100 m a des TROUS côtiers (entrée du Golfe, ports) que le
        # 20 m résout. En pool=True, la valeur fine = MAX de 3×3 sous-points
        # du pas de la maille (équivalent max-pooling : les chenaux étroits
        # survivent).
        base = self.grids[-1].window(west, south, east, north, max_px=max_px, pool=pool)
        if base is None or len(self.grids) == 1:
            return base
        sub, lngs, lats, step = base
        sub = np.array(sub, dtype=np.float32, copy=True)
        pitch_lat = abs(float(lats[1] - lats[0])) if len(lats) > 1 else abs(self.grids[-1].dy) * step
        pitch_lng = abs(float(lngs[1] - lngs[0])) if len(lngs) > 1 else self.grids[-1].dx * step
        for g in reversed(self.grids[:-1]):
            w, s, e, n = g.bounds
            selr = (lats >= s) & (lats <= n)
            selc = (lngs >= w) & (lngs <= e)
            if not selr.any() or not selc.any():
                continue
            ii = np.ix_(selr, selc)
            la_sub, lo_sub = np.meshgrid(lats[selr], lngs[selc], indexing="ij")
            step_g = max(1, int(round(pitch_lat / abs(g.dy))))
            if pool and step_g > 1:
                # VRAI max-pooling de la grille fine au pas de la maille :
                # fenêtre fine poolée sur l'intersection, puis alignement au
                # plus proche sur les centres de la maille grossière.
                s2, n2 = float(lats[selr].min()), float(lats[selr].max())
                w2, e2 = float(lngs[selc].min()), float(lngs[selc].max())
                pad = pitch_lat
                cells = max(
                    (n2 - s2 + 2 * pad) / abs(g.dy),
                    (e2 - w2 + 2 * pad) / g.dx,
                )
                fw = g.window(
                    w2 - pad, s2 - pad, e2 + pad, n2 + pad,
                    max_px=max(1, math.ceil(cells / step_g)), pool=True,
                )
                if fw is None:
                    continue
                fsub, flngs, flats, _fs = fw
                fdy = float(flats[1] - flats[0]) if len(flats) > 1 else g.dy * step_g
                fdx = float(flngs[1] - flngs[0]) if len(flngs) > 1 else g.dx * step_g
                iy = np.clip(np.round((la_sub - flats[0]) / fdy).astype(np.int64), 0, len(flats) - 1)
                ix = np.clip(np.round((lo_sub - flngs[0]) / fdx).astype(np.int64), 0, len(flngs) - 1)
                vals = fsub[iy, ix]
            else:
                vals = g.sample(la_sub, lo_sub)
            sub[ii] = vals
        return sub, lngs, lats, step


AnyGrid = Union[BathyGrid, MosaicGrid]

_grid: Optional[AnyGrid] = None
_zone_grids: dict[str, BathyGrid] = {}


def get_grid() -> Optional[AnyGrid]:
    """Singleton paresseux — mosaïque des zones ingérées (None si aucune)."""
    global _grid
    if _grid is None:
        grids: list[BathyGrid] = []
        for name, npy_name, meta_name in ZONE_FILES:
            npy_p, meta_p = DATA_DIR / npy_name, DATA_DIR / meta_name
            if npy_p.exists() and meta_p.exists():
                g = BathyGrid(meta_p, npy_p, name=name)
                _zone_grids[name] = g
                grids.append(g)
        if grids:
            _grid = grids[0] if len(grids) == 1 else MosaicGrid(grids)
    return _grid


def get_zone_grid(name: str) -> Optional[BathyGrid]:
    """Grille d'UNE zone précise (ex. champ « distance au large » des
    seamarks, calculé par zone)."""
    get_grid()
    return _zone_grids.get(name)


# ── Isobathes ───────────────────────────────────────────────────────────
# Niveaux affichés selon le zoom Leaflet : peu de lignes dézoomé (lisible),
# de plus en plus de détail en zoomant (retour armateur 20/07, vidéo
# Navionics : lignes fines + libellés de profondeur).
ISOBATH_LEVELS: list[tuple[int, list[float]]] = [
    (9,  [20.0, 50.0]),
    (10, [10.0, 20.0, 50.0]),
    (11, [5.0, 10.0, 20.0, 50.0]),
    (12, [5.0, 10.0, 20.0, 30.0, 50.0]),
    (13, [2.0, 5.0, 10.0, 20.0, 30.0, 50.0]),
    (14, [1.0, 2.0, 3.0, 5.0, 10.0, 15.0, 20.0, 30.0, 50.0]),
]
ISOBATH_LEVELS_MAX = [1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0, 50.0]


def levels_for_zoom(z: int) -> list[float]:
    for zmax, levels in ISOBATH_LEVELS:
        if z <= zmax:
            return levels
    return ISOBATH_LEVELS_MAX


def isobaths_geojson(
    west: float, south: float, east: float, north: float, zoom: int,
) -> dict:
    """FeatureCollection de LineString {depth} pour la bbox/zoom."""
    grid = get_grid()
    features: list[dict] = []
    if grid is None:
        return {"type": "FeatureCollection", "features": features}
    win = grid.window(west, south, east, north, max_px=420)
    if win is None:
        return {"type": "FeatureCollection", "features": features}
    depth, lngs, lats, _step = win
    if depth.shape[0] < 3 or depth.shape[1] < 3:
        return {"type": "FeatureCollection", "features": features}

    from contourpy import contour_generator

    z = np.ma.masked_invalid(depth)
    gen = contour_generator(x=lngs, y=lats, z=z)
    for level in levels_for_zoom(zoom):
        for line in gen.lines(level):
            if len(line) < 4:
                continue
            coords = [[round(float(x), 5), round(float(y), 5)] for x, y in line]
            features.append({
                "type": "Feature",
                "properties": {"depth": level},
                "geometry": {"type": "LineString", "coordinates": coords},
            })
    return {"type": "FeatureCollection", "features": features}
