"""SignalMar — Utilitaires Overpass PARTAGÉS (22/07/2026, fix 429 Atlantique).

L'ingestion de la façade Atlantique entière a fait tomber Overpass en
« 429 Too Many Requests ». Règles appliquées ici pour TOUTES les ingestions :
- découpage en tuiles ≤ TILE_DEG ;
- CACHE DISQUE par tuile (data/bathy/overpass_cache/) → reprise après crash
  sans re-télécharger, ré-exécution idempotente ;
- rotation de MIROIRS + backoff exponentiel, Retry-After honoré sur 429 ;
- pause de politesse entre tuiles.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parent.parent / "data" / "bathy"
CACHE = DATA / "overpass_cache"

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
UA = "SignalMar/1.0 ingestion cartographique (app marine communautaire)"
TILE_DEG = 1.0      # taille max d'une tuile Overpass
PAUSE_S = 6.0       # politesse entre tuiles (évite le 429 préventif)


def tiles(s: float, w: float, n: float, e: float,
          tile_deg: float = TILE_DEG) -> list[tuple[float, float, float, float]]:
    """Découpe l'emprise (s,w,n,e) en tuiles ≤ tile_deg."""
    out = []
    ny = max(1, math.ceil((n - s) / tile_deg))
    nx = max(1, math.ceil((e - w) / tile_deg))
    for iy in range(ny):
        for ix in range(nx):
            out.append((
                s + (n - s) * iy / ny, w + (e - w) * ix / nx,
                s + (n - s) * (iy + 1) / ny, w + (e - w) * (ix + 1) / nx,
            ))
    return out


def fetch(query: str, cache_key: str, timeout: float = 240.0) -> list[dict]:
    """Exécute une requête Overpass avec cache disque + retries robustes.

    ``cache_key`` doit identifier la requête ET la tuile (ex.
    ``islands_atl100_2_3``). Supprimer data/bathy/overpass_cache/ pour forcer
    un rafraîchissement complet.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    cpath = CACHE / f"{cache_key}.json"
    if cpath.exists():
        try:
            return json.loads(cpath.read_text())["elements"]
        except Exception:
            cpath.unlink()  # cache corrompu (crash en cours d'écriture)
    last: Exception | None = None
    for attempt in range(8):
        url = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            r = httpx.post(url, data={"data": query},
                           headers={"User-Agent": UA}, timeout=timeout)
            if r.status_code == 429:
                ra = r.headers.get("Retry-After", "")
                wait = min(float(ra) if ra.isdigit() else 30.0 * (attempt + 1), 180.0)
                print(f"  429 sur {url} → pause {wait:.0f}s", flush=True)
                last = RuntimeError(f"429 {url}")
                time.sleep(wait)
                continue
            r.raise_for_status()
            els = r.json().get("elements", [])
            tmp = cpath.with_suffix(".tmp")
            tmp.write_text(json.dumps({"elements": els}))
            tmp.replace(cpath)          # écriture atomique
            time.sleep(PAUSE_S)
            return els
        except Exception as exc:
            last = exc
            wait = min(10.0 * (attempt + 1), 90.0)
            print(f"  tentative {attempt + 1} ({url}) : {exc} → pause {wait:.0f}s", flush=True)
            time.sleep(wait)
    raise last  # type: ignore[misc]
