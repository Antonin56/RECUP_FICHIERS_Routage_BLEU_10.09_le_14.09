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
            content=_CLEAR_PNG, media_type="image/png",
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
DALLES_MIN_Z = 8
# PNG 1×1 TOTALEMENT transparent (alpha 0 — _BLANK_PNG historique est à 50 %).
_CLEAR_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
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
        return _CLEAR_PNG
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
        return _png_response(_CLEAR_PNG, 30 * 86400)

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
            content=_CLEAR_PNG, media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )
    return _png_response(data, 30 * 86400)


# ── 08/09/2026 (MASTER PLAN données armateur) — CARTES HORS LIGNE ──────────
# 1. /dalles-list?poly=lat,lng;lat,lng;… → dalles 20 m de l'index OVH
#    intersectant le polygone dessiné (nom, bbox, taille) ;
# 2. /dalles-npy/{name} → fichier .npy servi depuis le cache serveur
#    (téléchargé de l'OVH au besoin) pour stockage SUR LE TÉLÉPHONE ;
# 3. /dalles-fine-list?bbox= → dalles FINES 5 m/2 m si l'index OVH les
#    publie (clé « tiles_fine », prêt pour la chaîne PC v3) — sinon [].
import re as _re

_DALLE_NAME_RE = _re.compile(r"^tile_(-?\d+\.\d)_(-?\d+\.\d)\.npy$")


def _point_in_poly(lat: float, lng: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (xi > lng) != (xj > lng) and lat < (yj - yi) * (lng - xi) / (xj - xi + 1e-12) + yi:
            inside = not inside
        j = i
    return inside


@router.get("/dalles-list")
async def dalles_list(poly: str):
    try:
        pts = [tuple(float(v) for v in p.split(",")) for p in poly.split(";")]
        assert len(pts) >= 3 and all(len(p) == 2 for p in pts)
    except Exception:
        raise HTTPException(422, "poly invalide — attendu lat,lng;lat,lng;… (≥ 3 points)")

    def _work():
        from core.tile_bathy import get_remote_grid

        rg = get_remote_grid()
        if rg is None:
            return None
        s = min(p[0] for p in pts); n = max(p[0] for p in pts)
        w = min(p[1] for p in pts); e = max(p[1] for p in pts)
        out = []
        for name, meta in rg.store.tiles.items():
            bw, bs, be, bn = meta["bbox"]
            if be < w or bw > e or bn < s or bs > n:
                continue
            # Dalle retenue si un coin/centre est dans le polygone, ou si un
            # sommet du polygone tombe dans la dalle.
            corners = [(bs, bw), (bs, be), (bn, bw), (bn, be),
                       ((bs + bn) / 2, (bw + be) / 2)]
            hit = any(_point_in_poly(la, lo, pts) for la, lo in corners) or any(
                bs <= la <= bn and bw <= lo <= be for la, lo in pts)
            if hit:
                out.append({"name": name, "bbox": meta["bbox"],
                            "size_bytes": 1_000_128})
        return out

    tiles = await asyncio.to_thread(_work)
    if tiles is None:
        raise HTTPException(503, "Serveur de dalles injoignable — réessayez.")
    return {"tiles": tiles, "total_bytes": sum(t["size_bytes"] for t in tiles)}


@router.get("/dalles-npy/{name}")
async def dalles_npy(name: str):
    if not _DALLE_NAME_RE.match(name):
        raise HTTPException(422, "Nom de dalle invalide.")

    def _work():
        from core.tile_bathy import get_remote_grid

        rg = get_remote_grid()
        if rg is None or name not in rg.store.tiles:
            return None
        path = rg.store._ensure_file(name)
        if path is None:
            return None
        return path.read_bytes()

    data = await asyncio.to_thread(_work)
    if data is None:
        raise HTTPException(404, "Dalle indisponible.")
    return Response(
        content=data, media_type="application/octet-stream",
        headers={"Cache-Control": "public, max-age=2592000, immutable",
                 "Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/dalles-fine-list")
async def dalles_fine_list(bbox: str):
    try:
        w, s, e, n = [float(v) for v in bbox.split(",")]
    except Exception:
        raise HTTPException(422, "bbox invalide — attendu west,south,east,north")

    def _work():
        from core.tile_bathy import get_remote_grid

        rg = get_remote_grid()
        fine = (getattr(rg.store, "index_raw", None) or {}).get("tiles_fine") if rg else None
        if not fine:
            return []
        out = []
        for name, meta in fine.items():
            bw, bs, be, bn = meta["bbox"]
            if be < w or bw > e or bn < s or bs > n:
                continue
            out.append({"name": name, "bbox": meta["bbox"],
                        "level": meta.get("level", ""),
                        "size_bytes": meta.get("size_bytes", 0)})
        return out

    return {"tiles": await asyncio.to_thread(_work)}
