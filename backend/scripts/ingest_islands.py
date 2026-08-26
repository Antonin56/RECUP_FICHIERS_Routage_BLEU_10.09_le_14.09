"""SignalMar — Ingestion des ÎLES/ÎLOTS OSM → masque terre (v2, 23/07/2026).

Bug armateur « route sur TERRE » (Er Lannic) : le MNT SHOM ne couvre pas
certains îlots (cellules « eau » sur l'emprise réelle de l'île). On rasterise
les polygones OSM place=island|islet de la zone dans un masque booléen à la
résolution de la grille bathy (True = terre), puis on passe ces cellules à
NaN dans la grille (jamais navigables).

v2 (consigne superviseur, 23/07/2026) :
- GÉNÉRIQUE par zone (``--zone morbihan|atl100``) : l'emprise est dérivée des
  métadonnées de la grille cible — AUCUNE coordonnée codée en dur. Le même
  processus s'appliquera à toute future zone (France puis international).
- Requêtes Overpass DÉCOUPÉES en tuiles ≤ 1.2° (grandes emprises).
- AUTO-VÉRIFICATION après rasterisation : chaque île OSM NOMMÉE doit avoir
  son point représentatif masqué (voisinage 3×3). Rapport d'anomalies écrit
  dans data/bathy/land_mask_{zone}_report.json ; EXIT 1 si une île « grande »
  (> 200 m) échoue → bloque la livraison.
- Note cause racine du faux « décalage ~200 m » : la projection WGS84 →
  indices de grille était CORRECTE (écart mesuré 20-35 m = quantification de
  la grille 20 m) ; c'étaient les coordonnées de contrôle codées en dur qui
  étaient fausses (point en mer à 250 m de l'îlot). D'où la vérification
  systématique par polygones OSM ci-dessous.

Usage : python scripts/ingest_islands.py [--zone morbihan]
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx  # noqa: F401  (compat anciens imports)
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from overpass import fetch as overpass_fetch, tiles as overpass_tiles  # noqa: E402

DATA = ROOT / "data" / "bathy"

# Une entrée par grille bathy chargée. Toute NOUVELLE zone de navigation doit
# être ajoutée ici puis ingérée AVANT livraison (cf. tests/test_island_land_mask.py).
ZONES: dict[str, dict[str, str]] = {
    "morbihan": {
        "meta": "bathy_morbihan.json",
        "npy": "bathy_morbihan.npy",
        "orig": "bathy_morbihan_orig.npy",
        "mask": "land_mask.npy",
    },
    "atl100": {
        "meta": "bathy_atl100.json",
        "npy": "bathy_atl100.npy",
        "orig": "bathy_atl100_orig.npy",
        "mask": "land_mask_atl100.npy",
    },
    # Lorient-Groix 20 m (Litto3D BZH, 26/08/2026) — le lidar résout déjà la
    # terre finement, le bake OSM reste appliqué par sécurité (îlots).
    "lorient": {
        "meta": "bathy_lorient.json",
        "npy": "bathy_lorient.npy",
        "orig": "bathy_lorient_orig.npy",
        "mask": "land_mask_lorient.npy",
    },
}

ENDPOINTS = [  # conservé pour référence — le fetch passe par scripts/overpass.py
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
UA = "SignalMar/1.0 ingestion cartographique (app marine communautaire)"
TILE_DEG = 0.5  # 22/07 : 1.0° → 504 systématiques (relations « out geom » lourdes)


def _tiles(s: float, w: float, n: float, e: float) -> list[tuple[float, float, float, float]]:
    """Découpe l'emprise en tuiles ≤ TILE_DEG (Overpass tient la charge)."""
    return overpass_tiles(s, w, n, e, TILE_DEG)


def _fetch_tile(zone: str, idx: int, bbox: tuple[float, float, float, float]) -> list[dict]:
    """22/07/2026 — délégué à scripts/overpass.py : cache disque par tuile
    (reprise après crash), rotation de miroirs, backoff 429 (Retry-After),
    pause de politesse. Voir l'incident « 429 façade Atlantique »."""
    s, w, n, e = bbox
    query = f"""
[out:json][timeout:120];
(
  way["place"~"^(island|islet)$"]({s},{w},{n},{e});
  relation["place"~"^(island|islet)$"]({s},{w},{n},{e});
);
out geom;
"""
    return overpass_fetch(query, f"islands_{zone}_{idx}")


def _stitch_rings(members: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Assemble les ways « outer » d'une relation multipolygone en anneaux
    fermés (raccord glouton par extrémités). Les échecs sont ignorés."""
    rings: list[list[tuple[float, float]]] = []
    segs = [list(m) for m in members if len(m) >= 2]
    while segs:
        ring = segs.pop(0)
        changed = True
        while changed and ring[0] != ring[-1]:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring.extend(s[1:]); segs.pop(i); changed = True; break
                if s[-1] == ring[-1]:
                    ring.extend(reversed(s[:-1])); segs.pop(i); changed = True; break
                if s[-1] == ring[0]:
                    ring = s[:-1] + ring; segs.pop(i); changed = True; break
                if s[0] == ring[0]:
                    ring = list(reversed(s[1:])) + ring; segs.pop(i); changed = True; break
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def _collect_rings(els: list[dict]) -> tuple[list[list[tuple[float, float]]], list[str]]:
    rings: list[list[tuple[float, float]]] = []
    names: list[str] = []
    for el in els:
        name = (el.get("tags") or {}).get("name", "?")
        if el["type"] == "way":
            geom = el.get("geometry") or []
            pts = [(g["lat"], g["lon"]) for g in geom]
            if len(pts) >= 4:
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                rings.append(pts)
                names.append(name)
        elif el["type"] == "relation":
            outers = []
            for m in el.get("members", []):
                if m.get("role") == "outer" and m.get("geometry"):
                    outers.append([(g["lat"], g["lon"]) for g in m["geometry"]])
            got = _stitch_rings(outers)
            rings.extend(got)
            names.extend([name] * len(got))
    return rings, names


def _interior_point(ring: list[tuple[float, float]]) -> tuple[float, float]:
    """Point GARANTI À L'INTÉRIEUR du polygone (ray-casting à la latitude
    médiane, plus large intervalle intérieur). La moyenne des sommets tombe
    EN MER pour les îles concaves (cas Île-aux-Moines, 23/07)."""
    lat_mid = 0.5 * (min(p[0] for p in ring) + max(p[0] for p in ring))
    xs: list[float] = []
    for i in range(len(ring) - 1):
        (a_lat, a_lng), (b_lat, b_lng) = ring[i], ring[i + 1]
        if (a_lat > lat_mid) != (b_lat > lat_mid):
            t = (lat_mid - a_lat) / (b_lat - a_lat)
            xs.append(a_lng + t * (b_lng - a_lng))
    xs.sort()
    if len(xs) >= 2:
        best = max(range(0, len(xs) - 1, 2), key=lambda i: xs[i + 1] - xs[i])
        return lat_mid, (xs[best] + xs[best + 1]) / 2
    return (
        sum(p[0] for p in ring) / len(ring),
        sum(p[1] for p in ring) / len(ring),
    )


def _verify(
    rings: list[list[tuple[float, float]]], names: list[str],
    mask: np.ndarray, x0: float, y0: float, dx: float, dy: float,
) -> dict:
    """AUTO-VÉRIFICATION (consigne superviseur) : le point représentatif de
    chaque île NOMMÉE doit être masqué terre (voisinage 3×3). Une île
    « grande » (bbox > 200 m) qui échoue = anomalie BLOQUANTE."""
    cell_m = abs(dy) * 110_574.0
    fails_big: list[dict] = []
    fails_small: list[dict] = []
    checked = 0
    for ring, name in zip(rings, names):
        if name == "?":
            continue
        checked += 1
        la, lo = _interior_point(ring)
        r, c = int((la - y0) / dy), int((lo - x0) / dx)
        if not (0 <= r < mask.shape[0] and 0 <= c < mask.shape[1]):
            continue  # île en bord d'emprise, partiellement hors grille
        ok = bool(mask[max(0, r - 1):r + 2, max(0, c - 1):c + 2].any())
        if ok:
            continue
        span_m = max(
            (max(p[0] for p in ring) - min(p[0] for p in ring)) * 110_574.0,
            (max(p[1] for p in ring) - min(p[1] for p in ring)) * 111_320.0 * math.cos(math.radians(la)),
        )
        entry = {"name": name, "lat": round(la, 5), "lng": round(lo, 5), "span_m": round(span_m)}
        (fails_big if span_m > 200.0 else fails_small).append(entry)
    return {"checked_named": checked, "fails_big": fails_big, "fails_small": fails_small}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone", default="morbihan", choices=sorted(ZONES))
    args = ap.parse_args()
    cfg = ZONES[args.zone]
    meta_path = DATA / cfg["meta"]
    if not meta_path.exists():
        print(f"grille {args.zone} absente ({meta_path.name}) — ingérer le MNT d'abord.")
        sys.exit(2)
    meta = json.loads(meta_path.read_text())
    ncols, nrows = meta["ncols"], meta["nrows"]
    x0, y0, dx, dy = meta["x0"], meta["y0"], meta["dx"], meta["dy"]
    S, N, W, E = y0 + dy * nrows, y0, x0, x0 + dx * ncols

    tiles = _tiles(S, W, N, E)
    print(f"zone={args.zone} bbox=({S:.3f},{W:.3f},{N:.3f},{E:.3f}) — {len(tiles)} tuile(s) Overpass…")
    seen: set[tuple[str, int]] = set()
    els: list[dict] = []
    for i, t in enumerate(tiles):
        got = _fetch_tile(args.zone, i, t)
        fresh = [e for e in got if (e["type"], e["id"]) not in seen]
        seen.update((e["type"], e["id"]) for e in got)
        els.extend(fresh)
        print(f"  tuile {i + 1}/{len(tiles)} : {len(got)} éléments ({len(fresh)} nouveaux)", flush=True)

    rings, names = _collect_rings(els)
    print(f"{len(els)} éléments OSM → {len(rings)} anneaux fermés")

    # 22/07/2026 — SURÉCHANTILLONNAGE ×4 pour les grilles grossières : la
    # rasterisation PIL à maille native 100 m DÉBORDAIT (~300 m de mer marquée
    # terre à l'est d'Er Lannic dans le masque atl100). On rasterise à K× la
    # résolution puis on ne garde que les cellules couvertes à ≥ 50 %.
    cell_m = abs(dy) * 110_574.0
    K = 4 if cell_m > 50.0 else 1
    img = Image.new("1", (ncols * K, nrows * K), 0)
    draw = ImageDraw.Draw(img)
    for ring in rings:
        xy = [(((lng - x0) / dx) * K, ((lat - y0) / dy) * K) for lat, lng in ring]
        draw.polygon(xy, fill=1)
    if K == 1:
        mask = np.array(img, dtype=bool)
    else:
        mask = np.zeros((nrows, ncols), dtype=bool)
        band = 512
        for r0 in range(0, nrows, band):
            r1 = min(nrows, r0 + band)
            sub = np.asarray(img.crop((0, r0 * K, ncols * K, r1 * K)), dtype=np.uint8)
            mask[r0:r1] = sub.reshape(r1 - r0, K, ncols, K).sum(axis=(1, 3)) >= (K * K + 1) // 2
    cell_km2 = abs(dx * dy) * 110_574.0 * 111_320.0 * math.cos(math.radians((S + N) / 2)) / 1e6
    np.save(DATA / cfg["mask"], mask)
    print(f"{cfg['mask']} : {mask.shape}, {int(mask.sum())} cellules terre "
          f"({mask.sum() * cell_km2:.1f} km²)")

    # ── AUTO-VÉRIFICATION (bloquante pour les grandes îles) ───────────────
    report = _verify(rings, names, mask, x0, y0, dx, dy)
    report["zone"] = args.zone
    report["rings"] = len(rings)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    (DATA / f"land_mask_{args.zone}_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(f"vérification : {report['checked_named']} îles nommées, "
          f"{len(report['fails_big'])} échec(s) BLOQUANT(S) (> 200 m), "
          f"{len(report['fails_small'])} petit(s) îlot(s) non résolus (< 200 m)")
    for f in report["fails_big"]:
        print(f"  ⛔ {f['name']} ({f['lat']},{f['lng']}, {f['span_m']} m) NON masquée")

    # ── BAKE : cellules terre → NaN directement dans la grille bathy ──────
    npy = DATA / cfg["npy"]
    orig = DATA / cfg["orig"]
    if not orig.exists():
        shutil.copy2(npy, orig)
        print(f"sauvegarde originale → {orig.name}")
    grid = np.load(orig)  # repartir de l'original (ré-exécution idempotente)
    before = int(np.isfinite(grid).sum())
    grid[mask] = np.nan
    after = int(np.isfinite(grid).sum())
    np.save(npy, grid)
    print(f"{cfg['npy']} : {before - after} cellules « eau » passées à NaN "
          f"(terre OSM). Redémarrer le backend pour recharger.")

    if report["fails_big"]:
        print("⛔ ÉCHEC vérification îles — livraison bloquée.")
        sys.exit(1)


if __name__ == "__main__":
    main()
