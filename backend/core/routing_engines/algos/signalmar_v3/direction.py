"""SignalMar — Moteur C : SENS CONVENTIONNEL DÉTERMINISTE (03/08/2026).

RÈGLE 1 (priorité absolue, consigne armateur) : « le calcul doit toujours se
faire dans le sens conventionnel, de la mer vers la terre ; la géométrie
d'une route doit être identique dans les deux sens ».

Conséquence architecturale : le sens conventionnel n'est PLUS estimé par un
gradient au voisinage de chaque balise (c'est cette estimation qui faisait
passer le Moteur B du mauvais côté d'« Illur » le 03/08) — il EST le sens de
calcul. On ordonne donc les deux extrémités de façon déterministe :

* l'extrémité la plus AU LARGE devient le départ du calcul ;
* le tracé obtenu est retourné si l'utilisateur a demandé terre → mer.

« Au large » est mesuré par un champ « DISTANCE AU LARGE À TRAVERS L'EAU »
propre au Moteur C : BFS géodésique depuis les bordures en eau franche de la
grille bathymétrique **la plus FINE couvrant les deux extrémités**.

Pourquoi ne pas réutiliser ``SeamarkIndex._shelter`` ? Parce qu'il est calé
sur la grille ATL 100 m décimée ×8 (≈ 800 m par cellule) : à cette maille les
passes du Golfe du Morbihan sont FERMÉES, le BFS n'atteint pas l'intérieur du
Golfe et les valeurs y sont celles, propagées, de l'eau la plus proche —
mesuré le 03/08 : entrée de Port-Navalo 229,7 contre Le Hézo 226,9, soit un
sens conventionnel INVERSÉ. Sur la grille pilote (20 m, décimée ×8 ≈ 160 m)
les chenaux restent ouverts et le champ est monotone.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
from scipy import ndimage

from core.bathy import M_PER_DEG_LAT, get_grid, m_per_deg_lng

Pt = tuple[float, float]

#: Cible de taille du champ décimé (cellules par côté) — BFS instantané.
_TARGET_DIM = 700
#: Fond minimal d'une cellule de BORDURE pour être une graine « large » (m).
_SEED_DEPTH_M = 5.0
#: Écart minimal de « distance au large » pour trancher (itérations de BFS).
_SHELTER_EPS = 1.0

#: id(grille) → (champ décimé, pas de décimation, gradient sud, gradient est)
_FIELDS: dict[int, tuple[np.ndarray, int, np.ndarray, np.ndarray]] = {}


def _zone_grids() -> list[Any]:
    """Grilles disponibles, la plus FINE d'abord."""
    g = get_grid()
    if g is None:
        return []
    return list(getattr(g, "grids", [g]))


def grid_for(p1: Pt, p2: Pt) -> Optional[Any]:
    """Grille la plus FINE couvrant LES DEUX extrémités (comparabilité du
    champ), sinon la plus grossière disponible."""
    grids = _zone_grids()
    for gg in grids:
        if gg.covers(p1[0], p1[1]) and gg.covers(p2[0], p2[1]):
            return gg
    return grids[-1] if grids else None


def _field_for(grid) -> tuple[np.ndarray, int, np.ndarray, np.ndarray]:
    """Champ « distance au large » décimé + ses gradients (mis en cache)."""
    key = id(grid)
    cached = _FIELDS.get(key)
    if cached is not None:
        return cached
    ny, nx = grid.grid.shape
    step = max(1, int(math.ceil(max(ny, nx) / _TARGET_DIM)))
    depth = np.asarray(grid.grid[::step, ::step], dtype=np.float32)
    water = np.isfinite(depth) & (depth > 0.0)
    deep = water & (depth > _SEED_DEPTH_M)
    seeds = np.zeros_like(water)
    seeds[0, :] = deep[0, :]
    seeds[-1, :] = deep[-1, :]
    seeds[:, 0] = deep[:, 0]
    seeds[:, -1] = deep[:, -1]
    dist = np.full(water.shape, np.inf, dtype=np.float32)
    dist[seeds] = 0.0
    reached = seeds.copy()
    st = ndimage.generate_binary_structure(2, 2)
    it = 0
    max_it = water.shape[0] + water.shape[1]
    while it < max_it:
        it += 1
        nxt = ndimage.binary_dilation(reached, structure=st) & water & ~reached
        if not nxt.any():
            break
        dist[nxt] = it
        reached |= nxt
    # Terre / cellules non atteintes : on propage la valeur de l'eau la plus
    # proche (le champ reste défini partout, comme dans core.seamarks).
    invalid = ~np.isfinite(dist)
    if invalid.all():
        dist = np.zeros_like(dist)
    elif invalid.any():
        _, (ir, ic) = ndimage.distance_transform_edt(invalid, return_indices=True)
        dist = dist[ir, ic]
    # Gradient LISSÉ : sert à orienter le sens conventionnel (vers l'abri).
    smooth = ndimage.gaussian_filter(dist, sigma=4.0)
    gy, gx = np.gradient(smooth)   # gy : vers le sud (lignes+), gx : vers l'est
    out = (dist, step, gy, gx)
    _FIELDS[key] = out
    return out


def landward_dir(lat: float, lng: float, grid) -> Optional[tuple[float, float]]:
    """Sens CONVENTIONNEL local (unitaire, est/nord) : vers l'abri (distance au
    large croissante). None si indéfini."""
    if grid is None or not hasattr(grid, "grid"):
        return None
    _field, step, gy, gx = _field_for(grid)
    r, c = grid.rc(lat, lng)
    rr = int(np.clip(r // step, 0, gy.shape[0] - 1))
    cc = int(np.clip(c // step, 0, gy.shape[1] - 1))
    de = float(gx[rr, cc])
    dn = float(-gy[rr, cc])
    n = math.hypot(de, dn)
    if n < 1e-9:
        return None
    return (de / n, dn / n)


def seaward_scores(p1: Pt, p2: Pt) -> Optional[tuple[float, float]]:
    """(distance au large de p1, de p2) sur une MÊME grille. None si indispo."""
    grid = grid_for(p1, p2)
    if grid is None or not hasattr(grid, "grid"):
        return None
    field, step, _gy, _gx = _field_for(grid)
    vals = []
    for lat, lng in (p1, p2):
        r, c = grid.rc(lat, lng)
        rr = int(np.clip(r // step, 0, field.shape[0] - 1))
        cc = int(np.clip(c // step, 0, field.shape[1] - 1))
        vals.append(float(field[rr, cc]))
    return vals[0], vals[1]


def canonical_order(start: Pt, end: Pt) -> tuple[Pt, Pt, bool]:
    """(a, b, reversed) où a→b est le sens CONVENTIONNEL (mer → terre).

    ``reversed=True`` signifie que l'utilisateur a demandé b→a : le tracé
    calculé devra être retourné avant d'être rendu."""
    sc = seaward_scores(start, end)
    if sc is not None and abs(sc[0] - sc[1]) >= _SHELTER_EPS:
        # Le plus AU LARGE (distance au large la plus faible) part en premier.
        return (start, end, False) if sc[0] < sc[1] else (end, start, True)
    # Indécidable (même bassin, champ indisponible) : ordre lexicographique
    # STABLE — l'important est que les deux sens donnent le même couple.
    return (start, end, False) if start <= end else (end, start, True)


def heading_at(pts: list[Pt], seg_index: int, mlng: float) -> tuple[float, float]:
    """Vecteur unitaire (est, nord) du segment ``seg_index`` du tracé."""
    i = max(0, min(seg_index, len(pts) - 2))
    a, b = pts[i], pts[i + 1]
    ex = (b[1] - a[1]) * mlng
    en = (b[0] - a[0]) * M_PER_DEG_LAT
    n = math.hypot(ex, en)
    if n < 1e-9:
        return (1.0, 0.0)
    return (ex / n, en / n)


def mid_mlng(pts: list[Pt]) -> float:
    la = [p[0] for p in pts]
    return m_per_deg_lng((min(la) + max(la)) / 2)


__all__ = ["canonical_order", "seaward_scores", "grid_for", "landward_dir",
           "heading_at", "mid_mlng"]
