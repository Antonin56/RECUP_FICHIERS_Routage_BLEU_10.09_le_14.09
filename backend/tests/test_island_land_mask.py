"""SignalMar — Suite de VÉRIFICATION ÎLES (consigne superviseur, 23/07/2026).

À exécuter AVANT TOUTE LIVRAISON : aucune route calculée ne doit pouvoir
traverser une île connue. Trois niveaux de contrôle :
  1. Les îles de référence sont TERRE dans le(s) land_mask*.npy ;
  2. depth_at() les voit non navigables (NaN) ;
  3. Des routes « tentées » au travers d'îles les contournent (polyligne
     échantillonnée tous les 10 m, zéro cellule terre).

Les points de référence sont des POINTS INTÉRIEURS vérifiés sur les polygones
OSM (jamais des coordonnées approximatives : cause du faux « décalage 200 m »
du 23/07). Les îles hors couverture actuelle sont SKIPPÉES et s'activeront
automatiquement à l'extension de zone (France entière puis international).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from core.bathy import DATA_DIR, get_grid  # noqa: E402
from core.routing import RouteError, compute_route  # noqa: E402

# (nom, lat, lng, petit îlot ? → tolérance voisinage ±60 m)
ISLANDS: list[tuple[str, float, float, bool]] = [
    # Zone pilote Morbihan (couverte)
    ("Er Lannic", 47.5684, -2.8969, True),
    ("Gavrinis", 47.5735, -2.8979, False),
    ("Île aux Moines", 47.5972, -2.8513, False),
    ("Île d'Arz", 47.5936, -2.8036, False),
    ("Belle-Île (Bangor)", 47.3286, -3.1750, False),
    ("Houat (bourg)", 47.3899, -2.9613, False),
    ("Hoëdic (bourg)", 47.3400, -2.8740, False),
    ("Île Dumet", 47.4115, -2.6215, True),
    # Zone étendue (skippées tant que la couverture ne les inclut pas)
    ("Groix (bourg)", 47.6386, -3.4640, False),
    ("Ouessant (centre)", 48.4570, -5.0700, False),
    ("Île de Sein (bourg)", 48.0378, -4.8520, True),
    ("Bréhat (bourg)", 48.8490, -3.0000, True),
    ("Île d'Yeu (centre)", 46.7100, -2.3450, False),
    ("Noirmoutier (bourg)", 46.9990, -2.2450, False),
    ("Île de Ré (Bois-Plage)", 46.1870, -1.3930, False),
]

# Masques par zone : (fichier meta, fichier masque)
ZONE_MASKS = [
    ("bathy_morbihan.json", "land_mask.npy"),
    ("bathy_atl100.json", "land_mask_atl100.npy"),
]

# Routes « tentées » AU TRAVERS d'une île — départ/arrivée en eau vérifiée.
# (nom, start, end)
ROUTE_CASES: list[tuple[str, tuple[float, float], tuple[float, float]]] = [
    ("devant Er Lannic O→E", (47.5655, -2.9075), (47.5685, -2.8875)),
    ("travers Île d'Arz N→S", (47.615, -2.800), (47.575, -2.810)),
    ("travers Houat O→E", (47.390, -2.990), (47.390, -2.930)),
    # Zone étendue (skip auto tant que non couverte)
    ("travers Groix N→S", (47.660, -3.480), (47.600, -3.480)),
    ("travers Belle-Île NO→SE", (47.400, -3.250), (47.280, -3.100)),
    ("travers Yeu NO→SE", (46.760, -2.400), (46.680, -2.300)),
]


def _is_land(grid, lat: float, lng: float, small: bool) -> bool:
    """Terre = depth_at None (NaN/land bake). Petits îlots : ±60 m tolérés
    (quantification de la grille sur un îlot de 1-2 cellules)."""
    offs = [0.0] if not small else [-0.0006, 0.0, 0.0006]
    for dla in offs:
        for dlo in offs:
            if grid.depth_at(lat + dla, lng + dlo) is None:
                return True
    return False


@pytest.mark.parametrize("name,lat,lng,small", ISLANDS, ids=[i[0] for i in ISLANDS])
def test_island_is_not_navigable(name, lat, lng, small):
    grid = get_grid()
    assert grid is not None, "grille bathy absente"
    if not grid.covers(lat, lng):
        pytest.skip(f"{name} hors couverture actuelle (zone à venir)")
    assert _is_land(grid, lat, lng, small), (
        f"{name} ({lat},{lng}) est NAVIGABLE dans la grille — île non masquée !"
    )


@pytest.mark.parametrize("meta_name,mask_name", ZONE_MASKS, ids=[m[1] for m in ZONE_MASKS])
def test_islands_in_land_mask(meta_name, mask_name):
    meta_path = DATA_DIR / meta_name
    mask_path = DATA_DIR / mask_name
    if not meta_path.exists() or not mask_path.exists():
        pytest.skip(f"zone {meta_name} non ingérée")
    meta = json.loads(meta_path.read_text())
    mask = np.load(mask_path, mmap_mode="r")
    x0, y0, dx, dy = meta["x0"], meta["y0"], meta["dx"], meta["dy"]
    s, n = y0 + dy * meta["nrows"], y0
    w, e = x0, x0 + dx * meta["ncols"]
    checked = 0
    for name, lat, lng, _small in ISLANDS:
        if not (s <= lat <= n and w <= lng <= e):
            continue
        r, c = int((lat - y0) / dy), int((lng - x0) / dx)
        got = bool(mask[max(0, r - 1):r + 2, max(0, c - 1):c + 2].any())
        assert got, f"{name} absente du masque terre {mask_name} (cellule {r},{c})"
        checked += 1
    assert checked > 0, f"aucune île de référence dans l'emprise de {meta_name}"


def _route_land_hits(grid, waypoints: list[dict]) -> int:
    """Nombre de points (pas 10 m) de la polyligne tombant sur une cellule
    terre d'un des masques îles."""
    masks = []
    for meta_name, mask_name in ZONE_MASKS:
        mp, kp = DATA_DIR / meta_name, DATA_DIR / mask_name
        if mp.exists() and kp.exists():
            meta = json.loads(mp.read_text())
            masks.append((meta, np.load(kp, mmap_mode="r")))
    hits = 0
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        seg_m = math.hypot(
            (b["lat"] - a["lat"]) * 110_574.0,
            (b["lng"] - a["lng"]) * 111_320.0 * math.cos(math.radians(a["lat"])),
        )
        nstep = max(2, int(seg_m / 10.0))
        for k in range(nstep + 1):
            t = k / nstep
            la = a["lat"] + (b["lat"] - a["lat"]) * t
            lo = a["lng"] + (b["lng"] - a["lng"]) * t
            for meta, mask in masks:
                r = int((la - meta["y0"]) / meta["dy"])
                c = int((lo - meta["x0"]) / meta["dx"])
                if 0 <= r < meta["nrows"] and 0 <= c < meta["ncols"]:
                    # 22/07/2026 — sémantique MOSAÏQUE : le masque le PLUS FIN
                    # couvrant le point fait foi (ordre de ZONE_MASKS), comme
                    # le moteur de routage. Les masques plus grossiers ne sont
                    # consultés que hors emprise fine.
                    if mask[r, c]:
                        hits += 1
                    break
    return hits


@pytest.mark.parametrize("name,start,end", ROUTE_CASES, ids=[r[0] for r in ROUTE_CASES])
def test_route_never_crosses_island(name, start, end):
    grid = get_grid()
    assert grid is not None, "grille bathy absente"
    if not (grid.covers(*start) and grid.covers(*end)):
        pytest.skip(f"{name} hors couverture actuelle (zone à venir)")
    try:
        result = compute_route(start[0], start[1], end[0], end[1], 1.5, 0.5, 10.0)
    except RouteError as exc:
        pytest.fail(f"{name} : route refusée ({exc.code}: {exc.message})")
    hits = _route_land_hits(grid, result["waypoints"])
    assert hits == 0, f"{name} : {hits} point(s) de la route SUR UNE ÎLE !"
