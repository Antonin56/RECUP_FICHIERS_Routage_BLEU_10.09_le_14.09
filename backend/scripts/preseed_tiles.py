"""SignalMar — PRÉ-CHARGEMENT des tuiles balisage OpenSeaMap (24/07/2026).

Demande armateur : « les balises disparaissent au zoom/dézoom ». Cause : à
chaque niveau de zoom Leaflet charge un NOUVEAU jeu de tuiles ; si l'amont
(tiles.openseamap.org) ou l'ingress échoue, la tuile reste vide. Solution
définitive : remplir le CACHE DISQUE du proxy backend (routers/tiles.py,
stale-if-error 7 jours + fallback stale) pour toute la zone pilote → les
tuiles sont servies localement, plus aucune dépendance réseau en mer.

Zone pilote : Bretagne Sud (Golfe du Morbihan, Quiberon, Houat/Hoedic,
Belle-Île) — z11→16 partout + z17 sur le cœur du Golfe.

Usage : python scripts/preseed_tiles.py  (long — lancer en arrière-plan)
Reprise sûre : les tuiles déjà en cache sont sautées (HIT disque instantané).
"""
from __future__ import annotations

import asyncio
import math
import sys
import time

import httpx

BASE = "http://localhost:8001/api/tiles/seamark"

# (west, south, east, north, zmin, zmax)
AREAS = [
    (-3.45, 47.20, -2.35, 47.75, 11, 16),   # Bretagne Sud élargie
    (-3.10, 47.48, -2.55, 47.70, 17, 17),   # cœur Golfe du Morbihan + Quiberon E
]
CONCURRENCY = 3
PAUSE_S = 0.12  # ~25 tuiles/s max au total — poli avec l'amont OpenSeaMap


def tiles_for(west: float, south: float, east: float, north: float, z: int):
    def xy(lat: float, lng: float) -> tuple[int, int]:
        n = 2 ** z
        x = int((lng + 180.0) / 360.0 * n)
        lr = math.radians(lat)
        y = int((1.0 - math.asinh(math.tan(lr)) / math.pi) / 2.0 * n)
        return x, y

    x0, y0 = xy(north, west)
    x1, y1 = xy(south, east)
    for x in range(min(x0, x1), max(x0, x1) + 1):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            yield z, x, y


async def main() -> None:
    todo = []
    for west, south, east, north, zmin, zmax in AREAS:
        for z in range(zmin, zmax + 1):
            todo.extend(tiles_for(west, south, east, north, z))
    print(f"preseed: {len(todo)} tuiles seamark à garantir en cache", flush=True)
    ok = err = 0
    t0 = time.time()
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=30) as client:
        async def one(z: int, x: int, y: int) -> None:
            nonlocal ok, err
            async with sem:
                try:
                    r = await client.get(f"{BASE}/{z}/{x}/{y}.png")
                    if r.status_code == 200:
                        ok += 1
                    else:
                        err += 1
                except Exception:
                    err += 1
                await asyncio.sleep(PAUSE_S)

        batch = 400
        for i in range(0, len(todo), batch):
            await asyncio.gather(*(one(z, x, y) for z, x, y in todo[i:i + batch]))
            done = min(i + batch, len(todo))
            rate = done / max(1.0, time.time() - t0)
            eta_min = (len(todo) - done) / max(1.0, rate) / 60.0
            print(
                f"preseed: {done}/{len(todo)} (ok={ok} err={err}) "
                f"— {rate:.0f} t/s, ETA {eta_min:.0f} min",
                flush=True,
            )
    print(f"preseed TERMINÉ: ok={ok} err={err} en {(time.time()-t0)/60:.1f} min", flush=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
