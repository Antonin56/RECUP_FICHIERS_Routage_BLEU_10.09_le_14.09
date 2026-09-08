"""SignalMar — PROXY-CACHE de tuiles cartographiques (22/07/2026, GO armateur).

Le WMS SHOM est LENT (cause n°1 du lag tablette) et OpenSeaMap est
irrégulier. Ce routeur télécharge chaque tuile UNE fois, la stocke sur
disque, et la sert instantanément ensuite — avec des en-têtes HTTP de cache
longs pour que la WebView Leaflet ne redemande même plus.

- GET /api/tiles/shom/{key}/{z}/{x}/{y}.png   (key: atl|gdl|corse|morbihan)
  → GetMap WMS SHOM en EPSG:3857 (bbox calculée depuis z/x/y), cache ∞
    (la bathymétrie ne change pas).
- GET /api/tiles/seamark/{z}/{x}/{y}.png
  → tuile OpenSeaMap, cache 7 jours (le balisage évolue peu).

Public (tuiles de carte). Échec amont → PNG transparent 1×1 (cache court)
pour éviter les tempêtes de retries Leaflet.
"""
from __future__ import annotations

import asyncio
import base64
import math
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Path as FPath, Response

router = APIRouter(prefix="/tiles", tags=["tiles"])

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "tile_cache"
SHOM_WMS = "https://services.data.shom.fr/INSPIRE/wms/r"
SEAMARK_URL = "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"
SEAMARK_TTL_S = 7 * 86400

SHOM_LAYERS = {
    "atl": "MNT_ATL100m_HOMONIM_PBMA_3857_WMSR",
    "gdl": "MNT_MED100m_GDL_CA_HOMONIM_PBMA_3857_WMSR",
    "corse": "MNT_MED100m_CORSE_HOMONIM_PBMA_3857_WMSR",
    "morbihan": "MNT_COTIER_MORBIHAN_TANDEM_20m_PBMA_3857_WMSR",
}

# PNG transparent 1×1 (repli en cas d'échec amont).
_BLANK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

_sem = asyncio.Semaphore(12)          # politesse envers les serveurs amont
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=25.0,
            headers={"User-Agent": "SignalMar/1.0 tile-cache (app marine communautaire)"},
        )
    return _client


def _tile_bbox_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Bbox EPSG:3857 (minx, miny, maxx, maxy) d'une tuile XYZ."""
    size = 2 * math.pi * 6378137.0
    origin = size / 2.0
    res = size / (2 ** z)
    minx = -origin + x * res
    maxx = -origin + (x + 1) * res
    maxy = origin - y * res
    miny = origin - (y + 1) * res
    return minx, miny, maxx, maxy


def _png_response(data: bytes, max_age: int) -> Response:
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": f"public, max-age={max_age}, immutable"},
    )


async def _serve_cached(path: Path, fetch, ttl_s: float | None, max_age: int) -> Response:
    """Sert depuis le cache disque, sinon télécharge (dédupliqué par sémaphore).
    23/07 — résilience « balises qui disparaissent » : 2 tentatives amont,
    repli sur la version PÉRIMÉE du cache si l'amont échoue, et tuile blanche
    NON mise en cache navigateur (no-store) pour re-tenter au prochain passage."""
    try:
        if path.exists():
            if ttl_s is None or (time.time() - path.stat().st_mtime) < ttl_s:
                return _png_response(path.read_bytes(), max_age)
    except OSError:
        pass
    async with _sem:
        # Re-check : une autre requête a pu remplir le cache pendant l'attente.
        try:
            if path.exists() and (ttl_s is None or (time.time() - path.stat().st_mtime) < ttl_s):
                return _png_response(path.read_bytes(), max_age)
        except OSError:
            pass
        data = None
        for _ in range(2):  # une relance : l'amont (OpenSeaMap/SHOM) est irrégulier
            try:
                data = await fetch()
            except Exception:
                data = None
            if data:
                break
    if not data:
        # Amont indisponible : mieux vaut une tuile PÉRIMÉE que pas de balises.
        try:
            if path.exists():
                return _png_response(path.read_bytes(), 300)
        except OSError:
            pass
        return Response(
            content=_BLANK_PNG, media_type="image/png",
            headers={"Cache-Control": "no-store"},  # re-tenter très vite
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        pass
    return _png_response(data, max_age)


@router.get("/shom/{key}/{z}/{x}/{y}.png")
async def shom_tile(
    key: str,
    z: int = FPath(ge=3, le=19),
    x: int = FPath(ge=0),
    y: int = FPath(ge=0),
):
    layer = SHOM_LAYERS.get(key)
    if layer is None:
        raise HTTPException(404, "Couche inconnue.")
    if x >= 2 ** z or y >= 2 ** z:
        raise HTTPException(404, "Tuile hors grille.")
    path = CACHE_DIR / "shom" / key / str(z) / str(x) / f"{y}.png"

    async def fetch() -> bytes | None:
        minx, miny, maxx, maxy = _tile_bbox_3857(z, x, y)
        r = await _http().get(SHOM_WMS, params={
            "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
            "LAYERS": layer, "STYLES": "",
            "CRS": "EPSG:3857",
            "BBOX": f"{minx},{miny},{maxx},{maxy}",
            "WIDTH": "256", "HEIGHT": "256",
            "FORMAT": "image/png", "TRANSPARENT": "TRUE",
        })
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
            return r.content
        return None

    # Bathymétrie stable → cache disque sans expiration, HTTP 30 jours.
    return await _serve_cached(path, fetch, ttl_s=None, max_age=30 * 86400)


@router.get("/seamark/{z}/{x}/{y}.png")
async def seamark_tile(
    z: int = FPath(ge=3, le=18),
    x: int = FPath(ge=0),
    y: int = FPath(ge=0),
):
    if x >= 2 ** z or y >= 2 ** z:
        raise HTTPException(404, "Tuile hors grille.")
    path = CACHE_DIR / "seamark" / str(z) / str(x) / f"{y}.png"

    async def fetch() -> bytes | None:
        r = await _http().get(SEAMARK_URL.format(z=z, x=x, y=y))
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
            return r.content
        if r.status_code == 404:
            return _BLANK_PNG  # tuile vide côté OpenSeaMap (pas de balisage ici)
        return None

    return await _serve_cached(path, fetch, ttl_s=SEAMARK_TTL_S, max_age=7 * 86400)


# ── 08/09/2026 (remise à plat armateur, ACTION 4) — SURCOUCHE BATHY « DALLES
# OVH » : le calque bleu est RENDU PAR NOUS depuis les dalles .npy du serveur
# de l'armateur (core.tile_bathy), donc affiché PARTOUT où son index.json
# possède des dalles (chargement dynamique + cache disque, dalle manquante →
# transparent). En dessous de z10, tuile transparente (la couche WMS façade
# régionale prend le relais côté carte — coût réseau des dalles maîtrisé). ──
DALLES_MIN_Z = 10
_dalles_sem = asyncio.Semaphore(4)


def _render_dalles(rg, z: int, x: int, y: int) -> bytes | None:
    import io

    import numpy as np
    from PIL import Image

    minx, miny, maxx, maxy = _tile_bbox_3857(z, x, y)
    R = 6378137.0
    w, e = math.degrees(minx / R), math.degrees(maxx / R)
    s = math.degrees(math.atan(math.sinh(miny / R)))
    n = math.degrees(math.atan(math.sinh(maxy / R)))
    bw, bs, be, bn = rg.bounds
    if e <= bw or w >= be or n <= bs or s >= bn:
        return _BLANK_PNG
    N = 256
    ys = miny + (np.arange(N) + 0.5) * (maxy - miny) / N
    lats = np.degrees(np.arctan(np.sinh(ys / R)))[::-1]  # ligne 0 = nord
    lngs = w + (np.arange(N) + 0.5) * (e - w) / N
    d = rg.sample(np.repeat(lats, N), np.tile(lngs, N)).reshape(N, N)
    rgba = np.zeros((N, N, 4), dtype=np.uint8)
    fin = np.isfinite(d)
    # Estran / découvrant (−3,5 → −0,2 m au ZH) en vert d'estran ; terre
    # franche (< −3,5 m) et absence de donnée → TRANSPARENT (fond de carte).
    estran = fin & (d < -0.2) & (d >= -3.5)
    rgba[estran] = (134, 203, 171, 255)
    # Eau : du plus CLAIR (peu profond) au plus FONCÉ (profond).
    steps = (
        (2.0, (185, 225, 241)), (5.0, (143, 202, 233)),
        (10.0, (102, 175, 222)), (20.0, (66, 148, 210)),
        (50.0, (38, 118, 189)), (float("inf"), (21, 90, 163)),
    )
    water = fin & (d >= -0.2)
    lo = -0.2
    for hi, col in steps:
        m = water & (d >= lo) & (d < hi)
        rgba[m] = (col[0], col[1], col[2], 255)
        lo = hi
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@router.get("/dalles/{z}/{x}/{y}.png")
async def dalles_tile(
    z: int = FPath(ge=3, le=19),
    x: int = FPath(ge=0),
    y: int = FPath(ge=0),
):
    if x >= 2 ** z or y >= 2 ** z:
        raise HTTPException(404, "Tuile hors grille.")
    if z < DALLES_MIN_Z:
        return _png_response(_BLANK_PNG, 30 * 86400)

    def _work() -> bytes | None:
        from core.tile_bathy import get_remote_grid

        rg = get_remote_grid()
        if rg is None:
            return None
        ver = str(getattr(rg.store, "version", "0"))
        path = CACHE_DIR / "dalles" / ver / str(z) / str(x) / f"{y}.png"
        try:
            if path.exists():
                return path.read_bytes()
        except OSError:
            pass
        data = _render_dalles(rg, z, x, y)
        if data is None:
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError:
            pass
        return data

    async with _dalles_sem:
        data = await asyncio.to_thread(_work)
    if not data:
        # Serveur de dalles muet : tuile transparente NON mise en cache.
        return Response(
            content=_BLANK_PNG, media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )
    return _png_response(data, 30 * 86400)
