"""SignalMar — Ingestion Litto3D® Bretagne 2018-2021 → zone LORIENT-GROIX 20 m
(26/08/2026, demande armateur : maillage fin rade de Lorient + Groix).

Pourquoi Litto3D : AUCUN prépaquet « MNT côtier 20 m » SHOM ne couvre
Lorient/Groix (le TANDEM Morbihan s'arrête à lng −3.333). Le pack ouvert
LITTO3D_BZH_2018_2021 (lidar topo-bathy SHOM/IGN) couvre toute la côte
bretonne : on agrège son MNT 5 m en grille 20 m WGS84, même convention que
les autres zones (PROFONDEUR sous ZH, positive vers le bas, NaN = jamais
navigable).

⚠ RÉFÉRENCE VERTICALE : Litto3D est en altitude NGF-IGN69, PAS en ZH.
Conversion : depth_ZH = z0 − alt, où z0 = cote du ZH dans IGN69 (≈ −2.9 m à
Lorient), CALIBRÉE par médiane robuste contre l'ATL100 HOMONIM (PBMA) sur les
cellules franchement subtidales de recouvrement, et contrôlée (MAD).

Agrégation CONSERVATRICE : max-pooling de l'ALTITUDE (= fond le moins profond
du bloc) 5 m → 20 m — une roche de 5 m survit toujours à la décimation.

Espace disque limité (~4.6 Go libres) : les paquets .7z (~350 Mo pièce) sont
traités UN PAR UN puis SUPPRIMÉS ; la mosaïque intermédiaire est sauvée après
chaque paquet (reprise sûre via litto3d_state.json).

Usage : python scripts/ingest_litto3d_lorient.py
Sorties : data/bathy/bathy_lorient.npy + bathy_lorient.json
"""
from __future__ import annotations

import io
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import py7zr
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data" / "bathy"
WORK = DATA / "litto3d"
STATE = WORK / "litto3d_state.json"
ALT_NPY = WORK / "alt_l93_20m.npy"
OUT_NPY = DATA / "bathy_lorient.npy"
OUT_META = DATA / "bathy_lorient.json"

GROUP = "LITTO3D_BZH_2018_2021_PACK_DL"
BASE = ("https://services.data.shom.fr/INSPIRE/telechargement/"
        f"prepackageGroup/{GROUP}/prepackage")

# Emprise cible WGS84 (baie de Lorient + Groix, marge comprise).
W, S, E, N = -3.60, 47.55, -3.25, 47.79
DX = 0.0002          # ≈ 15 m lng / 22 m lat — même pas que la zone pilote
NCOLS = round((E - W) / DX)          # 1750
NROWS = round((N - S) / DX)          # 1200

# Paquets 5 km (nom = coin OUEST / bord NORD en km L93), calculés depuis le
# catalogue : pack (px,py) couvre X∈[px,px+5], Y∈[py-5,py].
TR_TO_L93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
_corners_x, _corners_y = TR_TO_L93.transform([W, E, W, E], [S, S, N, N])
XMIN, XMAX = min(_corners_x) / 1000, max(_corners_x) / 1000
YMIN, YMAX = min(_corners_y) / 1000, max(_corners_y) / 1000


# Armateur 26/08 : la VILLE de Lorient est inutile (« de l'entrée à la fin du
# port suffit ») — le port entier tient dans X ≤ 225 (colonnes 0205-0220).
# Colonne 0230 et 0225_6755+ = ville/Blavet/est de lng −3.333, déjà couverts
# par le TANDEM Morbihan 20 m (prioritaire dans la mosaïque). Les creux non
# couverts héritent de l'ATL100 via le rebouchage (aucune régression).
SKIP = {"0225_6755", "0225_6760", "0225_6765", "0230_6740", "0230_6745",
        "0230_6750", "0230_6755", "0230_6760", "0230_6765"}


def wanted_packs() -> list[str]:
    caps = json.loads((DATA / "l3d_bzh.xml").read_text())
    names = [p["prepackageName"] for p in caps["prepackageResources"]]
    out = []
    for n in names:
        px, py = (int(v) for v in n.split("_"))
        if px + 5 >= XMIN and px <= XMAX and py >= YMIN and py - 5 <= YMAX \
                and n not in SKIP:
            out.append(n)
    return sorted(out)


# Mosaïque L93 20 m de l'ALTITUDE IGN69 (max-pooling conservateur).
PACKS = wanted_packs()
MX0 = (min(int(p.split("_")[0]) for p in PACKS)) * 1000          # ouest, m
MX1 = (max(int(p.split("_")[0]) for p in PACKS) + 5) * 1000      # est
MY1 = (max(int(p.split("_")[1]) for p in PACKS)) * 1000          # nord
MY0 = (min(int(p.split("_")[1]) for p in PACKS) - 5) * 1000      # sud
MCOLS = (MX1 - MX0) // 20
MROWS = (MY1 - MY0) // 20


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"done": []}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state))


def download(pack: str, dest: Path) -> None:
    """Téléchargement avec REPRISE (Range) — SHOM coupe les gros paquets
    (Lorient-ville = 2.4 Go) en cours de transfert."""
    url = f"{BASE}/{pack}/file/{pack}.7z"
    part = dest.with_suffix(".part")
    total = None
    for attempt in range(25):
        done = part.stat().st_size if part.exists() else 0
        if total is not None and done >= total:
            break
        headers = {"Range": f"bytes={done}-"} if done else {}
        try:
            with httpx.stream("GET", url, timeout=600.0, headers=headers,
                              follow_redirects=True) as r:
                if r.status_code == 416:                    # déjà complet
                    break
                r.raise_for_status()
                if r.status_code == 206:
                    total = int(r.headers["Content-Range"].split("/")[-1])
                else:                                       # pas de Range → repart à 0
                    total = int(r.headers.get("Content-Length", 0)) or None
                    done = 0
                mode = "ab" if r.status_code == 206 else "wb"
                with open(part, mode) as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            if total is None or part.stat().st_size >= total:
                break
        except Exception as ex:                              # noqa: BLE001
            print(f"  retry {attempt + 1} {pack} "
                  f"({part.stat().st_size if part.exists() else 0:,}o) : {ex}",
                  flush=True)
            time.sleep(min(5 * (attempt + 1), 60))
    else:
        raise RuntimeError(f"téléchargement impossible : {pack}")
    part.replace(dest)


# ── PORTES DE CHENAL BALISÉ (27/08, GO armateur « correctif bathymétrie ») ──
# Le nettoyage 27/08 écrasait aussi de VRAIES sondes de banc au bord du
# balisage (Banc du Turc : natif 1.5-2.9 m remplacé par un ATL100 lissé
# ≥ 6 m, la maille 100 m moyennant banc et chenal) → le moteur ne « voyait »
# plus le danger que marquent les latérales N° 3 / Banc du Turc. Règle :
# une correction « eau profonde » n'est légitime que DANS LE CHENAL BALISÉ,
# c.-à-d. entre une latérale bâbord et sa latérale tribord la plus proche
# (porte ≤ 600 m). Hors porte = côté danger du balisage : le lidar fait foi.
GATE_MAX_M = 600.0     # largeur max d'une porte bâbord↔tribord
GATE_END_M = 25.0      # cœur de porte : abords immédiats des bouées exclus
GATE_HALF_M = 200.0    # demi-couloir le long de l'axe du chenal


def lateral_gate_mask(lats: np.ndarray, lngs: np.ndarray) -> np.ndarray:
    """True = cellule DANS une porte de chenal balisé.

    Portes = chaque latérale appariée à la latérale OPPOSÉE la plus proche
    (≤ GATE_MAX_M) — l'appariement au plus proche évite les fausses portes
    diagonales le long du chenal (ex. N° 4↔Banc du Turc) qui recouvriraient
    le banc lui-même. Couloir : cœur de porte (t ∈ [25 m, L−25 m]) élargi de
    ± 200 m perpendiculairement (le chenal continue entre deux portes)."""
    from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
    from core.seamarks import get_seamarks
    la0, la1 = float(lats.min()), float(lats.max())
    lo0, lo1 = float(lngs.min()), float(lngs.max())
    sel = [m for m in get_seamarks().marks
           if m.get("kind") == "lateral"
           and m.get("category") in ("port", "starboard")
           and la0 - 0.01 <= m["lat"] <= la1 + 0.01
           and lo0 - 0.01 <= m["lng"] <= lo1 + 0.01]
    ports = [(m["lat"], m["lng"]) for m in sel if m["category"] == "port"]
    stbds = [(m["lat"], m["lng"]) for m in sel if m["category"] == "starboard"]

    def _nearest(p, cands):
        best, bd = None, GATE_MAX_M
        for q in cands:
            d = math.hypot((p[0] - q[0]) * M_PER_DEG_LAT,
                           (p[1] - q[1]) * m_per_deg_lng(p[0]))
            if d <= bd:
                best, bd = q, d
        return best

    gates: set[tuple] = set()
    for p in ports:
        s = _nearest(p, stbds)
        if s is not None:
            gates.add((p, s))
    for s in stbds:
        p = _nearest(s, ports)
        if p is not None:
            gates.add((p, s))

    mask = np.zeros((lats.size, lngs.size), dtype=bool)
    for p, s in gates:
        mlng = m_per_deg_lng(p[0])
        pad_la = (GATE_HALF_M + GATE_END_M) / M_PER_DEG_LAT
        pad_lo = (GATE_HALF_M + GATE_END_M) / mlng
        la_lo, la_hi = min(p[0], s[0]) - pad_la, max(p[0], s[0]) + pad_la
        lo_lo, lo_hi = min(p[1], s[1]) - pad_lo, max(p[1], s[1]) + pad_lo
        r0 = max(int(np.searchsorted(-lats, -la_hi)), 0)          # lats ↓
        r1 = min(int(np.searchsorted(-lats, -la_lo)) + 1, lats.size)
        c0 = max(int(np.searchsorted(lngs, lo_lo)), 0)
        c1 = min(int(np.searchsorted(lngs, lo_hi)) + 1, lngs.size)
        if r0 >= r1 or c0 >= c1:
            continue
        gl, gn = np.meshgrid(lats[r0:r1], lngs[c0:c1], indexing="ij")
        px = (gn - p[1]) * mlng
        py = (gl - p[0]) * M_PER_DEG_LAT
        sx = (s[1] - p[1]) * mlng
        sy = (s[0] - p[0]) * M_PER_DEG_LAT
        L2 = max(sx * sx + sy * sy, 1e-9)
        L = math.sqrt(L2)
        t = (px * sx + py * sy) / L2
        perp = np.abs(px * sy - py * sx) / L
        tb = GATE_END_M / L
        mask[r0:r1, c0:c1] |= (t >= tb) & (t <= 1.0 - tb) & (perp <= GATE_HALF_M)
    print(f"portes de chenal balisé : {len(gates)} portes "
          f"({len(ports)} bâbord / {len(stbds)} tribord), "
          f"{int(mask.sum()):,} cellules en chenal", flush=True)
    return mask


def parse_asc(text: str) -> tuple[np.ndarray, float, float, float]:
    """→ (alt[nrows,ncols] NaN=nodata, xllcenter, yllcenter, cellsize)."""
    lines = text.splitlines()
    hdr = {}
    for i, ln in enumerate(lines[:8]):
        parts = ln.split()
        if len(parts) == 2 and parts[0].lower() in (
                "ncols", "nrows", "xllcenter", "yllcenter", "xllcorner",
                "yllcorner", "cellsize", "nodata_value"):
            hdr[parts[0].lower()] = float(parts[1])
        else:
            body_start = i
            break
    else:
        body_start = len(hdr)
    arr = np.loadtxt(io.StringIO("\n".join(lines[body_start:])),
                     dtype=np.float32)
    nod = hdr.get("nodata_value", -99999.0)
    arr[arr == np.float32(nod)] = np.nan
    cs = hdr["cellsize"]
    x0 = hdr.get("xllcenter", hdr.get("xllcorner", 0) + cs / 2)
    y0 = hdr.get("yllcenter", hdr.get("yllcorner", 0) + cs / 2)
    return arr, x0, y0, cs


def integrate_pack(pack: str, mosaic: np.ndarray) -> int:
    """Télécharge, extrait les MNT5m, max-pool l'altitude dans la mosaïque."""
    arc = WORK / f"{pack}.7z"
    if arc.exists():                       # cache : valider l'archive
        try:
            with py7zr.SevenZipFile(arc) as z:
                z.getnames()
        except Exception:
            print(f"  archive corrompue supprimée : {arc.name}", flush=True)
            arc.unlink()
    if not arc.exists():
        print(f"  téléchargement {pack}…", flush=True)
        download(pack, arc)
    with py7zr.SevenZipFile(arc) as z:
        targets = [n for n in z.getnames() if "/MNT5m/" in n and n.endswith(".asc")]
        z.extract(targets=targets, path=WORK / "tmp")
    n_cells = 0
    for asc in sorted((WORK / "tmp").rglob("*.asc")):
        alt, x0, y0, cs = parse_asc(asc.read_text())
        nr, nc = alt.shape
        # Centres des cellules 5 m (ligne 0 du fichier = NORD).
        xs = x0 + np.arange(nc, dtype=np.float64) * cs
        ys = y0 + (nr - 1 - np.arange(nr, dtype=np.float64)) * cs
        gx = ((xs - MX0) // 20).astype(np.int64)
        gy = ((MY1 - ys) // 20).astype(np.int64)
        ok_x = (gx >= 0) & (gx < MCOLS)
        ok_y = (gy >= 0) & (gy < MROWS)
        sub = alt[np.ix_(ok_y, ok_x)]
        gyy, gxx = np.meshgrid(gy[ok_y], gx[ok_x], indexing="ij")
        flat_idx = (gyy * MCOLS + gxx).ravel()
        vals = np.where(np.isnan(sub), -np.inf, sub).ravel()
        np.maximum.at(mosaic.reshape(-1), flat_idx, vals)
        n_cells += int(np.isfinite(sub).sum())
        asc.unlink()
    import shutil
    shutil.rmtree(WORK / "tmp", ignore_errors=True)
    arc.unlink()                                  # espace disque limité
    return n_cells


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    print(f"zone L93 : X {MX0}-{MX1}  Y {MY0}-{MY1}  mosaïque {MROWS}x{MCOLS}",
          flush=True)
    print(f"{len(PACKS)} paquets : {PACKS}", flush=True)
    state = load_state()
    if ALT_NPY.exists():
        mosaic = np.load(ALT_NPY)
    else:
        mosaic = np.full((MROWS, MCOLS), -np.inf, dtype=np.float32)
    for i, pack in enumerate(PACKS):
        if pack in state["done"]:
            continue
        t0 = time.time()
        n = integrate_pack(pack, mosaic)
        np.save(ALT_NPY, mosaic)
        state["done"].append(pack)
        save_state(state)
        print(f"[{i + 1}/{len(PACKS)}] {pack} : {n:,} cellules 5 m "
              f"({time.time() - t0:.0f} s)", flush=True)

    alt_l93 = np.where(np.isneginf(mosaic), np.nan, mosaic)
    print(f"mosaïque L93 : {np.isfinite(alt_l93).mean():.1%} couverte", flush=True)

    # ── Ré-échantillonnage → grille WGS84 (2×2 sous-points, max = conservateur)
    tr = TR_TO_L93
    lats = N + (np.arange(NROWS, dtype=np.float64) + 0.5) * -DX
    lngs = W + (np.arange(NCOLS, dtype=np.float64) + 0.5) * DX
    alt = np.full((NROWS, NCOLS), -np.inf, dtype=np.float32)
    subs = (-0.25, 0.25)
    for oy in subs:
        for ox in subs:
            la, lo = np.meshgrid(lats + oy * DX, lngs + ox * DX, indexing="ij")
            x, y = tr.transform(lo.ravel(), la.ravel())
            gx = ((np.asarray(x) - MX0) // 20).astype(np.int64)
            gy = ((MY1 - np.asarray(y)) // 20).astype(np.int64)
            ok = (gx >= 0) & (gx < MCOLS) & (gy >= 0) & (gy < MROWS)
            v = np.full(gx.shape, np.nan, dtype=np.float32)
            v[ok] = alt_l93[gy[ok], gx[ok]]
            v = np.where(np.isnan(v), -np.inf, v)
            alt = np.maximum(alt, v.reshape(NROWS, NCOLS))
    alt = np.where(np.isneginf(alt), np.nan, alt)

    # ── Calibration z0 (cote du ZH dans IGN69) ────────────────────────────
    # Référence primaire : TANDEM Morbihan (ZH natif, 20 m) sur le
    # recouvrement Gâvres→Étel (MAD ~0.15 m) ; repli : ATL100 (PBMA, 100 m).
    from core.bathy import get_zone_grid
    la, lo = np.meshgrid(lats, lngs, indexing="ij")
    atl = get_zone_grid("atl100")
    d_atl = atl.sample(la, lo)
    d_mor = get_zone_grid("morbihan").sample(la, lo)
    sel = np.isfinite(alt) & np.isfinite(d_mor) & (alt < -4.0) \
        & (d_mor >= 3.0) & (d_mor <= 40.0)
    ref = "TANDEM"
    if sel.sum() < 10_000:                                   # repli
        sel = np.isfinite(alt) & np.isfinite(d_atl) & (alt < -4.0) \
            & (d_atl >= 5.0) & (d_atl <= 30.0)
        ref = "ATL100"
    z0_samples = (d_mor if ref == "TANDEM" else d_atl)[sel] + alt[sel]
    z0 = float(np.median(z0_samples))
    mad = float(np.median(np.abs(z0_samples - z0)))
    print(f"calibration ZH/IGN69 vs {ref} : z0 = {z0:.2f} m  (n={sel.sum():,}, "
          f"MAD={mad:.2f} m)", flush=True)
    if not (-4.0 < z0 < -1.5) or mad > 1.2:
        raise SystemExit("calibration suspecte — ingestion REFUSÉE")

    depth = (z0 - alt).astype(np.float32)

    # ── Rebouchage des TROUS AU LARGE uniquement (hors couverture lidar) ────
    # ── Nettoyage des FAUX ASSÈCHES isolés (26/08) ─────────────────────────
    # Le lidar laisse des artefacts en pleine eau (bords de bandes de vol,
    # navires amarrés, glint) que le max-pooling conserve : cellules « à sec »
    # au milieu de 15 m d'eau. Règle : toute composante « assèche » de
    # ≤ 60 cellules dont l'ATL100 médian dit ≥ 5 m d'eau = artefact →
    # remplacée par l'ATL100. Les vrais bancs asséchants font des milliers de
    # cellules et l'ATL100 y est < 5 m : jamais touchés.
    from scipy.ndimage import distance_transform_edt, label, labeled_comprehension
    valid = np.isfinite(depth)
    dry = valid & (depth < 0.0)
    lab_d, n_d = label(dry, structure=np.ones((3, 3)))
    if n_d:
        sizes = np.bincount(lab_d.ravel())
        small = [i for i in range(1, n_d + 1) if sizes[i] <= 60]
        if small:
            med = labeled_comprehension(
                np.where(np.isfinite(d_atl), d_atl, -99.0), lab_d, small,
                np.median, float, -99.0)
            ghosts = {i for i, m in zip(small, med) if m >= 5.0}
            if ghosts:
                gm = np.isin(lab_d, list(ghosts))
                depth[gm] = d_atl[gm]
                print(f"faux assèches nettoyés (bruit lidar/navires) : "
                      f"{len(ghosts)} composantes, {int(gm.sum()):,} cellules",
                      flush=True)

    # ── Nettoyage des FAUSSES SURFACES lidar (27/08, GO armateur) ─────────
    # En eau turbide/agitée le lidar rend le NIVEAU D'EAU au lieu du fond :
    # cellules natives 0-3 m au beau milieu de passes à 10-20 m (ex. passe
    # Jument↔Citadelle), qui ferment la passe ET bloquent le rebouchage.
    # Règle validée armateur : natif ∈ [−0.5, 3 m) contredit par ATL100
    # (sondeur SHOM, autorité en eau profonde) ≥ 6 m → valeur ATL100,
    # UNIQUEMENT dans une porte de chenal balisé (correctif 27/08 : le
    # balisage latéral prime — hors porte, une sonde native peu profonde est
    # un vrai banc, ex. Banc du Turc, jamais « nettoyée »).
    in_gate = lateral_gate_mask(lats, lngs)
    valid = np.isfinite(depth)
    fake_surf = valid & (depth >= -0.5) & (depth < 3.0) \
        & np.isfinite(d_atl) & (d_atl >= 6.0) & in_gate
    if fake_surf.any():
        depth[fake_surf] = d_atl[fake_surf]
        print(f"fausses surfaces lidar nettoyées : {int(fake_surf.sum()):,} "
              f"cellules", flush=True)

    # ── Rebouchage des LACUNES LIDAR par l'ATL100 ──────────────────────────
    # Le lidar bathy ne pénètre pas les eaux profondes/turbides : le chenal
    # de la rade (10-20 m) est SANS donnée Litto3D. Règle : NaN comblé par
    # l'ATL100 partout où celui-ci répond, SAUF à ≤ 2 cellules d'une
    # terre/assèche vue par le lidar (on ne déborde jamais l'eau sur un quai
    # ou un banc précisément levés). Aucune « croûte » NaN autour des
    # lacunes : une route peut traverser du natif vers le comblé.
    valid = np.isfinite(depth)
    litto_dry = valid & (depth < 0.0)
    dist_dry = distance_transform_edt(~litto_dry)
    # 27/08 : dans les passes ÉTROITES flanquées de bancs réels (Jument↔
    # Citadelle), les lacunes de l'AXE étaient à ≤ 2 cellules d'une assèche
    # → jamais comblées → passe fermée. L'ATL100 ≥ 6 m fait autorité en eau
    # profonde (règle validée armateur) : on comble aussi dans ce cas — mais
    # UNIQUEMENT dans une porte de chenal balisé (même garde-fou que les
    # fausses surfaces : hors balisage, on ne creuse jamais près d'un banc).
    fill = (~valid) & np.isfinite(d_atl) \
        & ((dist_dry > 2.0) | ((d_atl >= 6.0) & in_gate))
    depth[fill] = d_atl[fill]
    print(f"lacunes rebouchées par ATL100 : {int(fill.sum()):,} cellules "
          f"({fill.mean():.2%})", flush=True)

    np.save(OUT_NPY, depth)
    OUT_META.write_text(json.dumps({
        "product": "LITTO3D_BZH_2018_2021_MNT5M_aggr20m_ZH",
        "license": "Licence Ouverte — Litto3D® © SHOM/IGN (non officiel navigation)",
        "ncols": NCOLS, "nrows": NROWS,
        "x0": W, "y0": N, "dx": DX, "dy": -DX,
        "z0_zh_ign69_m": round(z0, 3), "z0_mad_m": round(mad, 3),
        "z0_ref": ref,
        "offshore_filled_cells": int(fill.sum()),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    wet = depth[np.isfinite(depth)]
    print(f"OK {OUT_NPY.name} {NROWS}x{NCOLS} — couverture "
          f"{np.isfinite(depth).mean():.1%}, profondeur "
          f"{np.nanmin(wet):.1f}..{np.nanmax(wet):.1f} m", flush=True)


if __name__ == "__main__":
    main()
