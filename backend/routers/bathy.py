"""SignalMar — Isobathes SHOM (N1, 20/07/2026).

GET /api/bathy/isobaths?bbox=w,s,e,n&z=13 → GeoJSON FeatureCollection de
LineString avec ``properties.depth`` (m sous ZH). Lignes GÉNÉRÉES par nous
depuis le MNT SHOM ingéré (aucune couche isobathes dans le WMS open data).
Public (données ouvertes, aucune info utilisateur).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from core.bathy import get_grid, isobaths_geojson, levels_for_zoom

logger = logging.getLogger("signalmar.bathy")
router = APIRouter(prefix="/bathy", tags=["bathy"])


# ── 24/07/2026 (demande armateur) — HAUTEUR D'EAU AU POINT CLIQUÉ ──────────
# Clic court sur l'eau → fond carte (m / ZH) + marée actuelle + hauteur d'eau
# du moment. Nature des fonds : non disponible dans le MNT open data ingéré
# (repli hauteur d'eau seule, validé armateur).
@router.get("/depth")
async def depth_at_point(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    import asyncio as _asyncio
    import time as _time

    from core.tides import tide_window

    grid = get_grid()
    if grid is None or not grid.covers(lat, lng):
        return {"covered": False}
    d = grid.depth_at(lat, lng)
    if d is None:
        # Cellule sans donnée dans la couverture.
        return {"covered": True, "water": False}
    d = float(d)
    # Convention MNT : profondeur POSITIVE sous le ZH ; NÉGATIVE au-dessus
    # (estran découvrant jusqu'à ~-6 m, terre franche en dessous).
    if d < -7.0:
        return {"covered": True, "water": False}
    # 10/09/2026 (preuves armateur — « hallucination des profondeurs ») :
    # l'ancienne règle « minimum dans un rayon de ~25 m » (29/07) prenait la
    # cellule VOISINE la moins profonde — dans les chenaux à fort gradient
    # (maille 20 m, Golfe : 0,1 m → 18,5 m en 200 m) elle affichait jusqu'à
    # 13 m de MOINS que le fond sous le doigt (mesuré : 5,1 m affiché pour
    # 17,9 m réel) et CONTREDISAIT nos propres isobathes. Remplacée par une
    # interpolation BILINÉAIRE des 4 cellules encadrantes — la convention
    # EXACTE des lignes de niveau (contourpy) — bornée par prudence à la
    # valeur de la cellule la plus proche (jamais plus optimiste que la
    # carte affichée).
    try:
        import math as _math
        for _gr in (getattr(grid, "grids", None) or [grid]):
            if not _gr.covers(lat, lng):
                continue
            _fr = (lat - _gr.y0) / _gr.dy - 0.5
            _fc = (lng - _gr.x0) / _gr.dx - 0.5
            _r0, _c0 = int(_math.floor(_fr)), int(_math.floor(_fc))
            _wr, _wc = _fr - _r0, _fc - _c0
            _num = _den = 0.0
            for _dr in (0, 1):
                for _dc in (0, 1):
                    _r, _c = _r0 + _dr, _c0 + _dc
                    if not (0 <= _r < _gr.nrows and 0 <= _c < _gr.ncols):
                        continue
                    _v = float(_gr.grid[_r, _c])
                    if _math.isnan(_v):
                        continue
                    _wt = (_wr if _dr else 1.0 - _wr) * (_wc if _dc else 1.0 - _wc)
                    _num += _v * _wt
                    _den += _wt
            if _den > 1e-9:
                d = min(d, _num / _den)
            break
    except Exception:
        pass
    out: dict = {"covered": True, "water": True, "depth_zh_m": round(d, 1)}
    # Marée du moment (arrondie au pas de 10 min — même règle que le routage).
    # 28/07 (vidéo 15h45 « hauteur d'eau hyper lente, parfois rapide ») —
    # LATENCE BORNÉE : Open-Meteo froid peut prendre > 5 s ; au-delà de 2,5 s
    # on répond avec le fond carte seul (« marée indisponible ») plutôt que
    # de laisser la pastille mouliner. Les appels suivants tapent le cache.
    now = float(int(_time.time() // 600) * 600)
    try:
        tw = await _asyncio.wait_for(tide_window(lat, lng, now, 0.5), timeout=2.5)
    except Exception:
        tw = None
    if tw is not None:
        out["tide_m"] = tw["height_start_m"]
        out["height_now_m"] = round(d + tw["height_start_m"], 1)
        out["port"] = tw["port"]
    return out


@router.get("/isobaths")
async def get_isobaths(
    bbox: str = Query(..., description="west,south,east,north (EPSG:4326)"),
    z: int = Query(12, ge=3, le=19, description="zoom Leaflet"),
):
    try:
        parts = [float(p) for p in bbox.split(",")]
        west, south, east, north = parts
    except (ValueError, IndexError):
        raise HTTPException(422, "bbox invalide — attendu west,south,east,north")
    if west >= east or south >= north:
        raise HTTPException(422, "bbox invalide — ordre west<east, south<north")
    # Garde-fou : viewport max ~2°×2° (au-delà, trop dézoomé pour des lignes).
    if (east - west) > 2.5 or (north - south) > 2.5:
        return {"type": "FeatureCollection", "features": [], "levels": []}
    fc = isobaths_geojson(west, south, east, north, z)
    fc["levels"] = levels_for_zoom(z)
    return fc


@router.get("/coverage")
async def get_coverage():
    """Emprise(s) des grilles ingérées — pour l'app."""
    grid = get_grid()
    if grid is None:
        return {"available": False}
    w, s, e, n = grid.bounds
    zones = []
    for g in (grid.grids if hasattr(grid, "grids") else [grid]):
        zw, zs, ze, zn = g.bounds
        zones.append({
            "name": getattr(g, "name", ""),
            "product": g.product,
            "bounds": {"west": zw, "south": zs, "east": ze, "north": zn},
            "cell_deg": g.dx,
        })
    return {
        "available": True,
        "product": grid.product,
        "bounds": {"west": w, "south": s, "east": e, "north": n},
        "cell_deg": grid.dx,
        "zones": zones,
    }


# ── 22/07/2026 — BALISES CLIQUABLES : les seamarks OSM ingérées, servies par
# bbox pour l'overlay tactile de la carte (les tuiles OpenSeaMap sont du
# raster → impossible de taper dessus sans cette couche). Public. ─────────
@router.get("/seamarks")
async def get_seamarks_bbox(
    bbox: str = Query(..., description="west,south,east,north (EPSG:4326)"),
    # 09/09/2026 (V1.6, pack hors ligne) — plafond relevable jusqu'à 5000
    # pour télécharger TOUT le balisage/mouillages/dangers d'une zone.
    limit: int = Query(600, ge=1, le=5000),
):
    from core.seamarks import get_seamarks

    try:
        west, south, east, north = [float(p) for p in bbox.split(",")]
    except (ValueError, IndexError):
        raise HTTPException(422, "bbox invalide — attendu west,south,east,north")
    # 14/08 (audit QA FND-015) — bbox INVERSÉE (west > east ou south > north)
    # = 422 franc (avant : 200 avec liste vide, indiscernable d'une zone
    # réellement sans balise).
    if west > east or south > north:
        raise HTTPException(
            422, "bbox inversée — attendu west ≤ east et south ≤ north")
    idx = get_seamarks()
    if idx is None:
        return {"marks": []}
    marks = [
        {
            "id": m["id"],
            "lat": m["lat"],
            "lng": m["lng"],
            "kind": m["kind"],
            "type": m.get("type", ""),
            "category": m.get("category", ""),
            "colour": m.get("colour", ""),
            "name": m.get("name", ""),
            "light": m.get("light", ""),
        }
        for m in idx.marks
        if south <= m["lat"] <= north and west <= m["lng"] <= east
    ]
    # 22/07/2026 (lot armateur) — DANGERS cliquables : roches couvrantes/
    # découvrantes, épaves, obstructions (mêmes données que le moteur de route).
    hazards = [
        {
            "id": h["id"],
            "lat": h["lat"],
            "lng": h["lng"],
            "kind": h["kind"],
            "type": h.get("type", ""),
            "category": h.get("category", ""),
            "colour": "",
            "name": h.get("name", ""),
            "light": "",
            "water_level": h.get("water_level", ""),
            "depth_m": h.get("depth_m"),
        }
        for h in idx.hazards
        if south <= h["lat"] <= north and west <= h["lng"] <= east
    ]
    # 26/07/2026 (demande armateur) — BOUÉES DE MOUILLAGE cliquables (mêmes
    # données que les zones interdites du moteur de route).
    moorings = [
        {
            "id": mo["id"],
            "lat": mo["lat"],
            "lng": mo["lng"],
            "kind": "mooring",
            "type": "mooring",
            "category": mo.get("category", ""),
            "colour": "",
            "name": mo.get("name", ""),
            "light": "",
        }
        for mo in getattr(idx, "moorings", [])
        if south <= mo["lat"] <= north and west <= mo["lng"] <= east
    ]
    return {"marks": (marks + hazards + moorings)[:limit]}


# ── 04/09/2026 (ordre armateur) — SOURCE DES DALLES PC (OVH / repli) ────────
# Statut de la source du lecteur de dalles core.tile_bathy (serveur OVH de
# l'armateur, repli archive locale). Affiché dans la fiche de détails de
# route ("Source : Serveur OVH (v2.0)" / "Source : Archive (Repli)").
# NB : les moteurs A-I n'utilisent PAS encore ces dalles (info de câblage).
@router.get("/tiles-source")
async def tiles_source():
    import asyncio as _asyncio

    from core.tile_bathy import get_tile_service, get_remote_grid

    def _info():
        info = get_tile_service().source_info()
        # 04/09/2026 (ordre armateur, VISUEL) — bornes [w, s, e, n] de la
        # couverture des dalles, lues dynamiquement depuis l'index OVH
        # (affichage bathy carte non restreint au Morbihan).
        rg = get_remote_grid()
        if rg is not None:
            info["bounds"] = [round(v, 4) for v in rg.bounds]
        return info

    # source_info peut déclencher un fetch réseau (index) au 1er appel →
    # thread pour ne pas bloquer l'event loop.
    return await _asyncio.to_thread(_info)
