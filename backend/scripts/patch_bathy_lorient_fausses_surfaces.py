"""SignalMar — PATCH CHIRURGICAL bathy Lorient (27/08/2026, ordre armateur).

Corrige UNIQUEMENT les artefacts « fausse surface » du lidar Litto3D dans le
chenal de Lorient (passe Jument↔Citadelle, chenal Kernével, grand chenal
jusqu'au port) SANS ré-ingestion globale : la bathymétrie par défaut est
``bathy_lorient_orig.npy`` (bake original 26/08, restauré), sur laquelle ce
script applique une liste EXPLICITE de cellules à corriger.

Provenance des coordonnées : diagnostic du 27/08 (fausses surfaces natives
∈ [−0,5, 3 m) et lacunes de l'axe, toutes contredites par l'ATL100 SHOM
≥ 6 m — 228 cellules le long du chenal, lat 47.6846..47.7430,
lng −3.3754..−3.3458). Valeur de remplacement = sonde ATL100 (autorité en
eau profonde).

GARDE-FOUS :
1. RESPECT DU BALISAGE LATÉRAL (ordre armateur) : toute cellule à MOINS DE
   200 m des bouées N° 3 (47.7202845, −3.3638107) ou Banc du Turc
   (47.7221894, −3.3639723) est IGNORÉE — le banc qu'elles marquent ne doit
   jamais être « creusé ».
2. Signature vérifiée : une cellule n'est corrigée que si la valeur de base
   est NaN (lacune) ou ∈ [−0,5, 3 m) (fausse surface). Sinon, ignorée.
3. Idempotent : relit toujours l'ORIGINAL, applique le patch, re-cuit le
   masque terre OSM (land_mask_lorient.npy) → bathy_lorient.npy.

Usage : python scripts/patch_bathy_lorient_fausses_surfaces.py
        (puis redémarrer le backend)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "bathy"
ORIG = DATA / "bathy_lorient_orig.npy"
MASK = DATA / "land_mask_lorient.npy"
OUT = DATA / "bathy_lorient.npy"
META = DATA / "bathy_lorient.json"

# Bouées latérales protégées (rayon 200 m) — ordre armateur 27/08.
PROTECTED_BUOYS = [
    ("N° 3", 47.7202845, -3.3638107),
    ("Banc du Turc", 47.7221894, -3.3639723),
]
PROTECT_M = 200.0

# (ligne, colonne, profondeur_ZH_m) — cellules « fausse surface »/lacune du
# chenal, valeur = ATL100. Voir provenance dans l'en-tête.
PATCH_CELLS: list[tuple[int, int, float]] = [
    (235,1267,8.58), (236,1267,8.58), (237,1266,7.18), (237,1267,7.18), (238,1266,7.18), (238,1267,7.18),
    (239,1267,7.18), (266,1271,6.98), (269,1265,6.68), (269,1266,6.68), (269,1267,6.68), (270,1263,6.68),
    (270,1264,6.68), (270,1265,6.68), (270,1266,6.68), (270,1267,6.68), (271,1261,7.73), (271,1262,7.73),
    (271,1263,6.68), (271,1264,6.68), (271,1267,6.68), (290,1233,6.40), (290,1234,6.40), (290,1235,6.40),
    (291,1232,6.40), (291,1233,6.40), (291,1234,6.40), (291,1235,6.40), (291,1236,6.40), (301,1228,8.07),
    (308,1208,7.19), (308,1209,7.19), (308,1210,7.19), (308,1211,7.19), (309,1206,6.33), (309,1207,6.33),
    (309,1208,7.19), (309,1209,7.19), (309,1210,7.19), (309,1211,7.19), (310,1206,6.33), (310,1207,6.33),
    (311,1206,6.33), (317,1242,7.50), (318,1161,6.38), (318,1162,6.38), (318,1241,7.50), (318,1242,7.50),
    (319,1162,6.38), (319,1232,6.98), (319,1241,7.50), (319,1242,7.50), (320,1232,6.98), (320,1241,7.50),
    (320,1242,7.50), (321,1194,7.98), (321,1196,7.98), (321,1240,7.50), (322,1240,8.58), (323,1239,8.58),
    (323,1240,8.58), (324,1239,8.58), (324,1240,8.58), (325,1239,8.58), (325,1240,8.58), (326,1239,8.58),
    (326,1240,8.58), (332,1238,6.53), (332,1239,6.53), (333,1238,6.53), (333,1239,6.53), (334,1238,6.53),
    (334,1239,6.53), (334,1240,6.53), (335,1239,6.53), (335,1240,6.53), (336,1239,6.53), (343,1217,6.18),
    (343,1218,6.18), (344,1217,6.18), (344,1218,6.18), (351,1163,9.18), (351,1167,9.18), (352,1168,7.28),
    (352,1209,6.38), (352,1210,6.38), (353,1168,7.28), (353,1169,7.28), (354,1168,7.28), (354,1169,7.28),
    (355,1169,7.28), (355,1170,7.28), (356,1169,7.28), (356,1170,7.28), (357,1169,7.28), (357,1170,7.28),
    (358,1168,7.28), (358,1169,7.28), (359,1168,7.28), (360,1168,7.28), (361,1168,7.28), (361,1169,7.28),
    (362,1170,7.38), (363,1171,7.38), (371,1168,7.23), (371,1169,7.23), (371,1170,7.23), (372,1168,10.18),
    (372,1169,10.18), (372,1170,10.18), (373,1168,10.18), (373,1169,10.18), (373,1170,10.18), (374,1168,10.18),
    (374,1169,10.18), (375,1168,10.18), (375,1169,10.18), (376,1168,10.18), (376,1169,10.18), (377,1168,19.68),
    (381,1168,19.68), (382,1168,18.28), (382,1169,18.28), (383,1168,18.28), (383,1169,18.28), (384,1168,18.28),
    (387,1163,8.00), (387,1164,8.00), (387,1165,8.00), (388,1163,8.00), (388,1164,8.00), (388,1165,8.00),
    (389,1163,8.00), (389,1164,8.00), (389,1165,8.00), (390,1175,15.76), (390,1176,15.76), (390,1177,6.41),
    (391,1176,15.76), (391,1177,6.41), (394,1158,9.68), (395,1157,9.68), (395,1158,9.68), (395,1159,9.68),
    (395,1171,22.38), (396,1157,9.68), (396,1158,9.68), (396,1159,9.68), (396,1160,9.68), (396,1170,22.38),
    (396,1171,22.38), (397,1159,9.76), (397,1160,9.76), (397,1170,13.75), (397,1171,13.75), (398,1159,9.76),
    (398,1160,9.76), (398,1161,9.76), (398,1169,13.75), (398,1170,13.75), (398,1171,13.75), (399,1160,9.76),
    (399,1161,9.76), (399,1162,9.76), (399,1169,13.75), (399,1170,13.75), (400,1162,9.76), (400,1163,17.26),
    (400,1169,13.75), (400,1170,13.75), (401,1162,9.76), (401,1163,17.26), (401,1169,13.75), (401,1170,13.75),
    (401,1171,13.75), (402,1152,6.41), (402,1153,6.41), (402,1154,6.41), (402,1155,6.41), (402,1156,6.41),
    (402,1157,6.79), (402,1158,6.79), (402,1159,6.79), (402,1162,6.79), (402,1170,14.28), (402,1171,14.28),
    (403,1152,6.41), (403,1156,6.41), (403,1157,6.79), (403,1161,6.79), (404,1171,14.28), (405,1171,14.28),
    (406,1171,14.28), (407,1171,8.85), (411,1148,15.58), (411,1149,15.58), (412,1148,18.37), (412,1149,18.37),
    (413,1148,18.37), (413,1149,18.37), (414,1148,18.37), (415,1148,18.37), (417,1143,10.53), (417,1144,10.53),
    (417,1145,10.53), (417,1146,10.53), (418,1143,10.53), (418,1144,10.53), (515,1123,6.19), (515,1124,6.19),
    (515,1125,6.19), (516,1123,6.19), (516,1124,6.19), (516,1125,6.19), (516,1126,6.19), (516,1127,6.19),
    (516,1128,6.18), (517,1128,6.01), (517,1130,6.01), (517,1131,6.01), (517,1132,7.23), (517,1133,7.23),
    (518,1128,6.01), (518,1130,6.01), (518,1131,6.01), (518,1132,7.23), (527,1123,6.63), (527,1124,6.63),
]


def main() -> None:
    if not ORIG.exists():
        sys.exit(f"{ORIG} absent — restaurer l'original avant de patcher.")
    meta = json.loads(META.read_text())
    w, n, dx = meta["x0"], meta["y0"], meta["dx"]
    depth = np.load(ORIG).copy()

    applied = skipped_sig = skipped_buoy = 0
    for r, c, v in PATCH_CELLS:
        lat, lng = n - r * dx, w + c * dx
        if any(math.hypot((lat - bla) * 111_320.0,
                          (lng - blo) * 111_320.0 * math.cos(math.radians(lat)))
               < PROTECT_M for _, bla, blo in PROTECTED_BUOYS):
            skipped_buoy += 1
            continue
        base = depth[r, c]
        if not (np.isnan(base) or (-0.5 <= base < 3.0)):
            skipped_sig += 1
            continue
        depth[r, c] = v
        applied += 1

    land = np.load(MASK)
    n_land = int((np.isfinite(depth) & land).sum())
    depth[land] = np.nan
    np.save(OUT, depth)
    print(f"patch appliqué : {applied} cellules corrigées, "
          f"{skipped_buoy} ignorées (< {PROTECT_M:.0f} m des bouées N° 3 / "
          f"Banc du Turc), {skipped_sig} ignorées (signature inattendue) ; "
          f"masque terre re-cuit ({n_land} cellules). "
          f"Redémarrer le backend pour recharger.")


if __name__ == "__main__":
    main()
