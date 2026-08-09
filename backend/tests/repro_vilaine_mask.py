"""Décomposition du masque navigable dans l'estuaire de la Vilaine (seuil 0.3 m)."""
import sys
import numpy as np
from scipy import ndimage
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from core.bathy import get_grid, M_PER_DEG_LAT, m_per_deg_lng
from core import seamarks as sm

grid = get_grid()
# Fenêtre embouchure → barrage : -2.50 → -2.36 / 47.47 → 47.53
win = grid.window(-2.52, 47.46, -2.35, 47.54, max_px=900)
depth, lngs, lats, step = win
lat_mid = float((lats[0] + lats[-1]) / 2)
cy = abs(float(lats[1] - lats[0])) * M_PER_DEG_LAT
cx = abs(float(lngs[1] - lngs[0])) * m_per_deg_lng(lat_mid)
print(f"fenêtre {depth.shape}, cellule {cy:.0f}x{cx:.0f} m, step {step}")

MIN_DEPTH = 0.3
STRICT = 4.0
nav_raw = np.isfinite(depth) & (depth >= MIN_DEPTH)

# marge latérale 10 m (palier final du routeur) → sous la maille → pas d'érosion
marks = sm.get_seamarks()
blocked = marks.rasterize_blocked(
    lats, lngs, m_per_deg_lng(lat_mid), M_PER_DEG_LAT,
    min_depth=MIN_DEPTH, strict_depth=STRICT, depth=depth,
)
nav = nav_raw & ~blocked

def connectivity(mask, label):
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), bool))
    # composante contenant l'embouchure (47.49, -2.50) et le point amont (47.500,-2.39)
    def cell(lat, lng):
        r = int(np.clip(np.searchsorted(-lats, -lat), 0, len(lats) - 1))
        c = int(np.clip(np.searchsorted(lngs, lng), 0, len(lngs) - 1))
        return r, c
    r1, c1 = cell(47.488, -2.505)   # embouchure (mer)
    r2, c2 = cell(47.5005, -2.3915) # amont, aval barrage
    r3, c3 = cell(47.497, -2.434)   # Tréhiguier (drapeau armateur)
    l1, l2, l3 = lab[r1, c1], lab[r2, c2], lab[r3, c3]
    print(f"{label}: embouchure lab={l1}, Tréhiguier lab={l3}, amont lab={l2} → "
          f"mer↔Tréhiguier {'CONNECTÉ' if l1 == l3 and l1 > 0 else 'COUPÉ'}, "
          f"mer↔amont {'CONNECTÉ' if l1 == l2 and l1 > 0 else 'COUPÉ'}")

connectivity(nav_raw, "PROFONDEUR SEULE (0.3 m)")
connectivity(nav, "PROFONDEUR + BALISAGE")

# Où le balisage bloque-t-il le chenal ? cellules d'eau navigable bloquées par les marks
cut = nav_raw & blocked
rr, cc = np.nonzero(cut)
if len(rr):
    # zones bloquées dans le chenal (profondeur >= 0.3) entre -2.47 et -2.40
    sel = (lngs[cc] > -2.47) & (lngs[cc] < -2.40)
    print(f"cellules d'eau bloquées par balisage dans le chenal: {sel.sum()}")
    if sel.sum():
        lo = np.argsort(lngs[cc[sel]])
        pts = list(zip(lats[rr[sel]][lo], lngs[cc[sel]][lo]))
        print("  exemples:", [(round(a,4), round(b,4)) for a, b in pts[:6]], "...", [(round(a,4), round(b,4)) for a, b in pts[-3:]])

# Balises proches du point de blocage (47.4963,-2.4525)
for m in marks.marks if hasattr(marks, "marks") else []:
    pass
