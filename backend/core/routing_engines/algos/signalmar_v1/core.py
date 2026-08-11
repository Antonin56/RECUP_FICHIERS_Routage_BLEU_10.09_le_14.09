"""SignalMar — Moteur de route sûre (V2 phase N1, 20/07/2026).

Calcule une route A → B qui respecte :
  profondeur(ZH) ≥ tirant d'eau + marge de profondeur   (masque navigable)
  distance aux zones interdites ≥ marge latérale        (dilatation morpho)

Algorithme : fenêtre décimée autour de A/B → masque navigable → dilatation
elliptique (marge latérale en cellules) → A* 8-connexe avec pénalité de
proximité des zones limites (la route « préfère » le milieu du chenal) →
lissage par ligne de vue (string pulling) → profil de profondeur échantillonné
sur la grille PLEINE résolution.

V2.0 : SANS marée (ZH = pire cas, conservateur). NaN (hors couverture
produit) = NON navigable par sécurité.
"""
from __future__ import annotations

import heapq
import math
from typing import Optional

import numpy as np
from scipy import ndimage

from core.bathy import BathyGrid, M_PER_DEG_LAT, get_grid, m_per_deg_lng
from core.nav_rules import DEPTH_PRIORITY
from core.seamarks import (
    MOORING_EXEMPT_M, MOORINGS_OPEN, R_MOORING_M, SIDE_ABSOLUTE, get_seamarks,
)

# Bornes serveur (mêmes que le profil bateau côté app).
DRAFT_MIN, DRAFT_MAX = 0.2, 4.0
DEPTH_MARGIN_MIN, DEPTH_MARGIN_MAX = 0.0, 3.0
# 22/07/2026 — minimum abaissé 50 → 10 m (demande armateur : 50 m fermait des
# chenaux étroits pourtant sûrs, ex. Belle-Île → Golfe).
LATERAL_MIN, LATERAL_MAX = 10.0, 500.0

MAX_DIM = 520          # taille max de la fenêtre A* grossière (cellules)
FINE_DIM = 420         # taille max des fenêtres de RAFFINEMENT par tronçon
PAD_FRAC = 0.35        # marge autour de la bbox A-B
PAD_MIN_DEG = 0.05     # ~5 km mini (détours autour des îles)
FINE_PAD_MIN_DEG = 0.015  # ~1.6 km autour d'un tronçon fin
SNAP_MAX_M = 400.0     # rattrapage du départ/arrivée vers l'eau navigable
SNAP_DEPTH_TOL_M = 45.0   # parmi les cellules à <= cette distance de la plus
                          # proche, on préfère la plus profonde (~3 mailles fines)
BLOCKED_DEPTH_TOL_M = 200.0  # idem, pour le point atteignable le plus proche
                             # de l'arrivée quand le tronçon est bloqué
# 22/07/2026 (bug armateur « je ne peux faire aucune route ») — destination
# posée sur l'estran / une zone découvrante (plage, port à sec à ZH) : on
# ACCROCHE l'arrivée à l'eau navigable la plus proche dans ce rayon au lieu
# de refuser sèchement. Au-delà → vrai end_blocked. 5 km : devant Damgan à
# marée basse, l'eau ≥ 2 m est à ~4 km de la plage (large estran du Mor Braz).
END_SNAP_MAX_M = 5000.0


def _trunc_cap_m(start: tuple[float, float], ref: dict) -> float:
    """26/07 (bug armateur « Foireuse 3 », Vilaine) — plafond de troncature
    « arrivée déplacée » ADAPTATIF : 5 km fixes refusaient une route de 52 km
    bloquée à 5,16 km de la destination (seuil découvrant de la Vilaine) →
    no_route sec au lieu d'une route livrée jusqu'au point atteignable.
    Cap = max(5 km, 15 % de la distance directe départ→destination), borné
    à 12 km (jamais de troncature absurde type Brest→La Rochelle)."""
    d = math.hypot(
        (start[0] - ref["lat"]) * M_PER_DEG_LAT,
        (start[1] - ref["lng"]) * m_per_deg_lng(ref["lat"]),
    )
    return min(12_000.0, max(END_SNAP_MAX_M, 0.15 * d))
# 23/07/2026 (bug armateur — départ posé à terre près de Locmariaquer) :
# composante d'eau < ce seuil = POCHE isolée (fausse eau du MNT, mare,
# bassin fermé) → l'extrémité est mauvaise, pas la route.
TRAP_POCKET_KM2 = 1.0
PENALTY_K = 0.6        # poids de la pénalité de proximité du danger
PROFILE_STEP_M = 100.0 # pas d'échantillonnage du profil de profondeur


class RouteError(Exception):
    def __init__(self, code: str, message: str, payload: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        # 22/07/2026 — données annexes (point de blocage, tronçon partiel…)
        # renvoyées telles quelles dans le détail HTTP 422.
        self.payload = payload


class _SnapFail(Exception):
    """Extrémité d'un tronçon non accrochable à l'eau navigable."""
    def __init__(self, which: str):
        self.which = which


class _LegBlocked(Exception):
    """A* impossible dans une fenêtre : point de blocage + tronçon atteignable."""
    def __init__(self, blocked_at: tuple[float, float], partial_pts: list[tuple[float, float]]):
        self.blocked_at = blocked_at
        self.partial_pts = partial_pts


def _window_for(
    grid: BathyGrid, a: tuple[float, float], b: tuple[float, float],
    max_px: int = MAX_DIM, pad_min: float = PAD_MIN_DEG, pool: bool = False,
    pad_frac: float = PAD_FRAC,
):
    lat_min, lat_max = min(a[0], b[0]), max(a[0], b[0])
    lng_min, lng_max = min(a[1], b[1]), max(a[1], b[1])
    span = max(lat_max - lat_min, lng_max - lng_min)
    pad = max(span * pad_frac, pad_min)
    win = grid.window(
        lng_min - pad, lat_min - pad,
        lng_max + pad, lat_max + pad,
        max_px=max_px, pool=pool,
    )
    if win is None:
        raise RouteError("out_of_coverage", "Zone hors couverture bathymétrique (façade Ouest : Manche Ouest → Pertuis charentais).")
    return win


def _cell_of(lats: np.ndarray, lngs: np.ndarray, lat: float, lng: float) -> tuple[int, int]:
    # lats décroissantes (nord → sud), lngs croissantes.
    r = int(np.clip(np.searchsorted(-lats, -lat), 0, len(lats) - 1))
    c = int(np.clip(np.searchsorted(lngs, lng), 0, len(lngs) - 1))
    return r, c


def _snap(
    nav: np.ndarray, r: int, c: int, cell_m: float,
    depth: Optional[np.ndarray] = None,
) -> Optional[tuple[int, int]]:
    """Cellule navigable la plus proche (≤ SNAP_MAX_M), ou None.

    Avec ``depth`` fourni : parmi les cellules à <= SNAP_DEPTH_TOL_M de la
    plus proche, on garde la plus profonde (jamais au-delà de SNAP_MAX_M) —
    évite d'accrocher une vasière voisine quand la cellule la plus proche
    n'est que marginalement navigable."""
    if nav[r, c]:
        return r, c
    rad = int(SNAP_MAX_M / cell_m) + 1
    best, best_d = None, None
    r0, r1 = max(0, r - rad), min(nav.shape[0], r + rad + 1)
    c0, c1 = max(0, c - rad), min(nav.shape[1], c + rad + 1)
    sub = nav[r0:r1, c0:c1]
    idx = np.argwhere(sub)
    if idx.size == 0:
        return None
    d2 = (idx[:, 0] + r0 - r) ** 2 + (idx[:, 1] + c0 - c) ** 2
    i = int(np.argmin(d2))
    if depth is not None:
        dist_m = np.sqrt(d2.astype(np.float64)) * cell_m
        near = np.flatnonzero(
            (dist_m <= dist_m[i] + SNAP_DEPTH_TOL_M) & (dist_m <= SNAP_MAX_M)
        )
        cand_depth = depth[idx[near, 0] + r0, idx[near, 1] + c0]
        finite = np.isfinite(cand_depth)
        if finite.any():
            i = near[finite][int(np.argmax(cand_depth[finite]))]
    best_d = math.sqrt(float(d2[i])) * cell_m
    if best_d > SNAP_MAX_M:
        return None
    best = (int(idx[i, 0] + r0), int(idx[i, 1] + c0))
    return best


def _astar(nav: np.ndarray, cost_extra: np.ndarray, start: tuple[int, int],
           goal: tuple[int, int], cy: float, cx: float) -> Optional[list[tuple[int, int]]]:
    """A* 8-connexe. cy/cx = taille de cellule en m (lignes/colonnes).

    27/07/2026 (perf, « hyper lent comparé à Navionics ») — le cœur est
    JIT-compilé avec numba (~30-80× plus rapide que la boucle Python) ;
    repli automatique sur l'implémentation Python si numba indisponible.
    Même algorithme, mêmes règles (pas de coupe de coin en diagonale)."""
    if _astar_nb is not None:
        parent = _astar_nb(
            nav.astype(np.uint8), cost_extra.astype(np.float64),
            start[0], start[1], goal[0], goal[1], float(cy), float(cx),
        )
        if parent[goal[0], goal[1], 0] < 0 and (start != goal):
            return None
        path = [(goal[0], goal[1])]
        r, c = goal
        while (r, c) != (start[0], start[1]):
            pr, pc = parent[r, c]
            if pr < 0:
                return None
            r, c = int(pr), int(pc)
            path.append((r, c))
        path.reverse()
        return path
    return _astar_py(nav, cost_extra, start, goal, cy, cx)


try:  # 27/07 — noyau A* compilé (numba). Import/compile isolés : repli Python sûr.
    from numba import njit

    # 02/08/2026 (armateur : « erreur 429 quasi à chaque calcul près des
    # côtes ») — nogil=True LIBÈRE LE GIL pendant l'A*. Le backend tourne avec
    # UN seul worker uvicorn : sans cela, un calcul côtier de plusieurs
    # secondes gelait la boucle d'événements, donc TOUTES les autres requêtes
    # (tuiles, marées, réessais du calcul lui-même) partaient en file d'attente
    # côté ingress → 429. Le résultat numérique est strictement identique
    # (nogil ne change que la gestion du verrou d'interpréteur).
    @njit(cache=True, nogil=True)
    def _astar_nb_core(nav, cost_extra, sr, sc, gr, gc, cy, cx):  # pragma: no cover
        ny, nx = nav.shape
        diag = (cy * cy + cx * cx) ** 0.5
        dr8 = np.array([-1, 1, 0, 0, -1, -1, 1, 1], dtype=np.int64)
        dc8 = np.array([0, 0, -1, 1, -1, 1, -1, 1], dtype=np.int64)
        w8 = np.array([cy, cy, cx, cx, diag, diag, diag, diag], dtype=np.float64)
        INF = np.inf
        gscore = np.full((ny, nx), INF, dtype=np.float64)
        parent = np.full((ny, nx, 2), -1, dtype=np.int32)
        closed = np.zeros((ny, nx), dtype=np.uint8)
        gscore[sr, sc] = 0.0
        # Tas binaire (f, r, c) sur tableaux plats.
        cap = 1024
        hf = np.empty(cap, dtype=np.float64)
        hr = np.empty(cap, dtype=np.int32)
        hc = np.empty(cap, dtype=np.int32)
        n = 0

        def push(f, r, c, n, hf, hr, hc):
            i = n
            hf[i] = f
            hr[i] = r
            hc[i] = c
            while i > 0:
                p = (i - 1) >> 1
                if hf[p] <= hf[i]:
                    break
                hf[p], hf[i] = hf[i], hf[p]
                hr[p], hr[i] = hr[i], hr[p]
                hc[p], hc[i] = hc[i], hc[p]
                i = p
            return n + 1

        def pop(n, hf, hr, hc):
            f0 = hf[0]
            r0 = hr[0]
            c0 = hc[0]
            n -= 1
            hf[0] = hf[n]
            hr[0] = hr[n]
            hc[0] = hc[n]
            i = 0
            while True:
                l = 2 * i + 1
                rgt = l + 1
                sm = i
                if l < n and hf[l] < hf[sm]:
                    sm = l
                if rgt < n and hf[rgt] < hf[sm]:
                    sm = rgt
                if sm == i:
                    break
                hf[sm], hf[i] = hf[i], hf[sm]
                hr[sm], hr[i] = hr[i], hr[sm]
                hc[sm], hc[i] = hc[i], hc[sm]
                i = sm
            return f0, r0, c0, n

        h0 = (((sr - gr) * cy) ** 2 + ((sc - gc) * cx) ** 2) ** 0.5
        n = push(h0, sr, sc, n, hf, hr, hc)
        pops = 0
        max_pops = ny * nx
        while n > 0:
            _f, r, c, n = pop(n, hf, hr, hc)
            if closed[r, c] == 1:
                continue
            closed[r, c] = 1
            pops += 1
            if pops > max_pops:
                break
            if r == gr and c == gc:
                return parent
            g0 = gscore[r, c]
            for k in range(8):
                r2 = r + dr8[k]
                c2 = c + dc8[k]
                if r2 < 0 or r2 >= ny or c2 < 0 or c2 >= nx:
                    continue
                if closed[r2, c2] == 1 or nav[r2, c2] == 0:
                    continue
                # Pas de coupe de coin en diagonale.
                if k >= 4 and (nav[r, c2] == 0 or nav[r2, c] == 0):
                    continue
                g2 = g0 + w8[k] * (1.0 + cost_extra[r2, c2])
                if g2 < gscore[r2, c2]:
                    gscore[r2, c2] = g2
                    parent[r2, c2, 0] = r
                    parent[r2, c2, 1] = c
                    if n >= cap:
                        cap2 = cap * 2
                        hf2 = np.empty(cap2, dtype=np.float64)
                        hr2 = np.empty(cap2, dtype=np.int32)
                        hc2 = np.empty(cap2, dtype=np.int32)
                        hf2[:n] = hf[:n]
                        hr2[:n] = hr[:n]
                        hc2[:n] = hc[:n]
                        hf = hf2
                        hr = hr2
                        hc = hc2
                        cap = cap2
                    f2 = g2 + (((r2 - gr) * cy) ** 2 + ((c2 - gc) * cx) ** 2) ** 0.5
                    n = push(f2, r2, c2, n, hf, hr, hc)
        # But jamais fermé : parent[goal] reste -1 → l'appelant échoue proprement,
        # sauf si le but a été atteint (retour anticipé ci-dessus).
        return parent

    _astar_nb = _astar_nb_core
except Exception:  # pragma: no cover
    _astar_nb = None


def _astar_py(nav: np.ndarray, cost_extra: np.ndarray, start: tuple[int, int],
              goal: tuple[int, int], cy: float, cx: float) -> Optional[list[tuple[int, int]]]:
    """A* 8-connexe (implémentation Python de repli)."""
    ny, nx = nav.shape
    moves = [(-1, 0, cy), (1, 0, cy), (0, -1, cx), (0, 1, cx),
             (-1, -1, math.hypot(cy, cx)), (-1, 1, math.hypot(cy, cx)),
             (1, -1, math.hypot(cy, cx)), (1, 1, math.hypot(cy, cx))]
    INF = np.inf
    gscore = np.full((ny, nx), INF, dtype=np.float64)
    parent = np.full((ny, nx, 2), -1, dtype=np.int32)
    sr, sc = start
    gr, gc = goal

    def h(r: int, c: int) -> float:
        return math.hypot((r - gr) * cy, (c - gc) * cx)

    gscore[sr, sc] = 0.0
    heap: list[tuple[float, int, int]] = [(h(sr, sc), sr, sc)]
    closed = np.zeros((ny, nx), dtype=bool)
    pops = 0
    max_pops = ny * nx  # garde-fou
    while heap:
        f, r, c = heapq.heappop(heap)
        if closed[r, c]:
            continue
        closed[r, c] = True
        pops += 1
        if pops > max_pops:
            return None
        if (r, c) == (gr, gc):
            path = [(r, c)]
            while (r, c) != (sr, sc):
                pr, pc = parent[r, c]
                r, c = int(pr), int(pc)
                path.append((r, c))
            path.reverse()
            return path
        g0 = gscore[r, c]
        for dr, dc, base in moves:
            r2, c2 = r + dr, c + dc
            if not (0 <= r2 < ny and 0 <= c2 < nx):
                continue
            if closed[r2, c2] or not nav[r2, c2]:
                continue
            # 23/07 — PAS de coupe de coin en diagonale : les deux voisins
            # orthogonaux doivent être navigables, sinon la ligne réelle
            # frôle/traverse la cellule bloquée (sur données 100 m, couper un
            # coin = 50 m au-dessus d'une roche → contrôles corridor en échec
            # en boucle, plateau de Penmarc'h).
            if dr != 0 and dc != 0 and not (nav[r, c2] and nav[r2, c]):
                continue
            g2 = g0 + base * (1.0 + cost_extra[r2, c2])
            if g2 < gscore[r2, c2]:
                gscore[r2, c2] = g2
                parent[r2, c2] = (r, c)
                heapq.heappush(heap, (g2 + h(r2, c2), r2, c2))
    return None


def _line_clear(nav: np.ndarray, a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Supercover : toutes les cellules traversées par le segment sont navigables."""
    r0, c0 = a
    r1, c1 = b
    n = int(max(abs(r1 - r0), abs(c1 - c0))) * 2 + 1
    for i in range(n + 1):
        t = i / n
        r = int(round(r0 + (r1 - r0) * t))
        c = int(round(c0 + (c1 - c0) * t))
        if not nav[r, c]:
            return False
    return True


def _round_corners(
    nav: np.ndarray, path: list[tuple[float, float]], iterations: int = 3,
) -> list[tuple[float, float]]:
    """21/07/2026 — léger ARRONDI des changements de cap (demande armateur :
    un bateau vire progressivement). Coupe chaque angle à 25 % de part et
    d'autre (type Chaikin) UNIQUEMENT si le raccourci reste en eau navigable
    (les virages contournent souvent un danger : jamais d'arrondi aveugle).
    22/07 : conservé pour le tracé PARTIEL (blocage) ; le tracé final est
    arrondi par _round_pts (contrôle couloir pleine résolution)."""
    def _ok(a: tuple[float, float], b: tuple[float, float]) -> bool:
        ia = (int(round(a[0])), int(round(a[1])))
        ib = (int(round(b[0])), int(round(b[1])))
        return nav[ia[0], ia[1]] and nav[ib[0], ib[1]] and _line_clear(nav, ia, ib)

    pts = [(float(r), float(c)) for r, c in path]
    for _ in range(iterations):
        if len(pts) < 3:
            break
        out = [pts[0]]
        changed = False
        for i in range(1, len(pts) - 1):
            a, b, c = out[-1], pts[i], pts[i + 1]
            b1 = (b[0] + 0.3 * (a[0] - b[0]), b[1] + 0.3 * (a[1] - b[1]))
            b2 = (b[0] + 0.3 * (c[0] - b[0]), b[1] + 0.3 * (c[1] - b[1]))
            if _ok(b1, b2) and _ok(a, b1) and _ok(b2, c):
                out.extend([b1, b2])
                changed = True
            else:
                out.append(b)
        out.append(pts[-1])
        pts = out
        if not changed:
            break
    return pts


def _smooth(nav: np.ndarray, path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """String pulling : supprime les points intermédiaires en ligne de vue."""
    if len(path) <= 2:
        return path
    out = [path[0]]
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1 and not _line_clear(nav, path[i], path[j]):
            j -= 1
        out.append(path[j])
        i = j
    return out


def _nav_for(
    depth: np.ndarray, lats: np.ndarray, lngs: np.ndarray,
    min_depth: float, lateral_margin_m: float, cy: float, cx: float, lat_mid: float,
    strict_depth: Optional[float] = None,
    strict_exempt: Optional[tuple] = None,
) -> np.ndarray:
    """Masque navigable : profondeur + marge latérale + balisage IALA."""
    nav_raw = np.isfinite(depth) & (depth >= min_depth)
    # 23/07 (extension de zone) — érosion « marge latérale » SEULEMENT si la
    # marge est significative devant la maille : l'ancien minimum d'1 cellule
    # scellait les détroits en fenêtre grossière (1 cellule = 200-700 m sur
    # l'ATL 100 m → sortie du Golfe fermée). Sous la demi-maille, la marge est
    # garantie par le raffinement fin + les corridors pleine résolution.
    ry = int(round(lateral_margin_m / cy))
    rx = int(round(lateral_margin_m / cx))
    if ry >= 1 or rx >= 1:
        ry, rx = max(1, ry), max(1, rx)
        yy, xx = np.ogrid[-ry:ry + 1, -rx:rx + 1]
        footprint = (yy / ry) ** 2 + (xx / rx) ** 2 <= 1.0
        nav = ~ndimage.binary_dilation(~nav_raw, structure=footprint)
    else:
        nav = nav_raw
    seamarks = get_seamarks()
    if seamarks is not None:
        nav &= ~seamarks.rasterize_blocked(
            lats, lngs, m_per_deg_lng(lat_mid), M_PER_DEG_LAT, min_depth=min_depth,
            strict_depth=strict_depth, depth=depth, strict_exempt=strict_exempt,
        )
        # ── 28/07/2026 (consigne support/armateur : « OBLIGATOIRE de suivre
        # les chenaux ») — CONTRAINTE DURE de porte de chenal, en complément
        # de la pénalité douce : de part et d'autre de chaque couple de
        # latérales rouge/verte, un MUR mince (le long de la ligne de porte)
        # INTERDIT l'eau PEU PROFONDE (fond < strict_depth) hors de la porte
        # (|s| > 0,7 × écartement), jusqu'à max(2,5 × écartement, 450 m).
        # Passer À CÔTÉ de la porte sur l'estran couvert / le petit fond est
        # IMPOSSIBLE (plus seulement coûteux — vidéo 15h45 : raccourci à
        # l'ouest des n°5/6/8 du chenal de Vannes). Le mur est MINCE le long
        # de l'axe : les chenaux qui tournent ne sont jamais scellés entre
        # deux portes. Maille fine uniquement ; exemption 400 m autour du
        # départ/de l'arrivée DEMANDÉS (manœuvres).
        if strict_depth is not None and max(cy, cx) <= 45.0:
            mlng = m_per_deg_lng(lat_mid)
            for (g_lat, g_lng, gap, ux, uy) in seamarks.gates(
                    float(lats[-1]), float(lats[0]), float(lngs[0]), float(lngs[-1])):
                if strict_exempt and any(
                    math.hypot((g_lat - p[0]) * M_PER_DEG_LAT,
                               (g_lng - p[1]) * mlng) < MOORING_EXEMPT_M
                    for p in strict_exempt
                ):
                    continue
                r_wall = max(2.5 * gap, 450.0)
                w_half = max(0.5 * gap, 1.5 * max(cy, cx))
                ry = int(math.ceil(r_wall / cy))
                rx = int(math.ceil(r_wall / cx))
                br = min(max(int(np.searchsorted(-lats, -g_lat)), 0), len(lats) - 1)
                bc = min(max(int(np.searchsorted(lngs, g_lng)), 0), len(lngs) - 1)
                r0, r1 = max(0, br - ry), min(len(lats), br + ry + 1)
                c0, c1 = max(0, bc - rx), min(len(lngs), bc + rx + 1)
                if r1 <= r0 or c1 <= c0:
                    continue
                dyy = (lats[r0:r1, None] - g_lat) * M_PER_DEG_LAT
                dxx = (lngs[None, c0:c1] - g_lng) * mlng
                s_tr = dxx * ux + dyy * uy       # transverse (le long de la porte)
                t_ax = dyy * ux - dxx * uy       # le long de l'axe du chenal
                sub_d = depth[r0:r1, c0:c1]
                with np.errstate(invalid="ignore"):
                    wall = (
                        (np.abs(t_ax) <= w_half)
                        & (np.abs(s_tr) > 0.7 * gap)
                        & (np.abs(s_tr) <= r_wall)
                        & np.isfinite(sub_d) & (sub_d < strict_depth)
                    )
                nav[r0:r1, c0:c1] &= ~wall
    return nav


def _to_latlng(lats: np.ndarray, lngs: np.ndarray, pts) -> list[tuple[float, float]]:
    lat0, lng0 = float(lats[0]), float(lngs[0])
    dlat = float(lats[1] - lats[0]) if len(lats) > 1 else 0.0
    dlng = float(lngs[1] - lngs[0]) if len(lngs) > 1 else 0.0
    return [(lat0 + r * dlat, lng0 + c * dlng) for r, c in pts]


def _solve_leg(
    grid: BathyGrid, a: tuple[float, float], b: tuple[float, float],
    min_depth: float, lateral_margin_m: float,
    *, max_px: int, pad_min: float, do_round: bool = True,
    strict_depth: Optional[float] = None,
    strict_exempt: Optional[tuple] = None,
    trap_check: bool = False,
    trap_end: bool = True,
    pad_frac: float = PAD_FRAC,
) -> dict:
    """A* dans UNE fenêtre autour de a→b (décimation MAX-POOLING : les chenaux
    étroits mais profonds survivent). Retourne {pts, raw, step} — pts = tracé
    latlng arrondi, raw = tracé lissé sans arrondi (base du raffinement).
    Lève _SnapFail / _LegBlocked (point de blocage + tronçon atteignable)."""
    depth, lngs, lats, step = _window_for(grid, a, b, max_px=max_px, pad_min=pad_min, pool=True,
                                          pad_frac=pad_frac)
    lat_mid = float((lats[0] + lats[-1]) / 2)
    cy = abs(float(lats[1] - lats[0])) * M_PER_DEG_LAT if len(lats) > 1 else abs(grid.dy) * M_PER_DEG_LAT
    cx = abs(float(lngs[1] - lngs[0])) * m_per_deg_lng(lat_mid) if len(lngs) > 1 else grid.dx * m_per_deg_lng(lat_mid)
    cell_m = min(cy, cx)
    nav = _nav_for(depth, lats, lngs, min_depth, lateral_margin_m, cy, cx, lat_mid,
                   strict_depth, strict_exempt)

    rs, cs = _cell_of(lats, lngs, a[0], a[1])
    rg, cg = _cell_of(lats, lngs, b[0], b[1])
    snap_s = _snap(nav, rs, cs, cell_m, depth)
    snap_g = _snap(nav, rg, cg, cell_m, depth)
    if snap_s is None:
        raise _SnapFail("start")
    if snap_g is None:
        raise _SnapFail("end")

    # Pénalité : attire la route vers le milieu des chenaux.
    dist_to_danger = ndimage.distance_transform_edt(nav, sampling=(cy, cx))
    # 23/07 (extension de zone) — d0 proportionnel à la MAILLE : en fenêtre
    # poolée grossière (200-700 m), le max-pooling « efface » les roches d'un
    # plateau (Chaussée de Sein) ; élargir le rayon de pénalité pousse la
    # passe grossière vers l'eau franchement libre, le raffinement fin fait
    # le reste. En zone pilote (maille 20-60 m), comportement inchangé.
    d0 = max(lateral_margin_m * 4.0, 200.0, 2.0 * max(cy, cx))
    prox = np.clip((d0 - dist_to_danger) / d0, 0.0, 1.0)
    cost_extra = (prox * PENALTY_K).astype(np.float64)
    # 29/07/2026 (retour test en mer — « pour un danger isolé sans côté
    # obligatoire, passer du CÔTÉ LE PLUS PROFOND ») : près des zones
    # bloquées (< d0), le coût est MAJORÉ là où l'eau est PEU PROFONDE →
    # à choix équivalent, l'A* contourne roches/dangers isolés par le côté
    # le plus profond et VIRE PLUS TÔT (la pénalité pousse au large avant
    # la bouée au lieu de raser le disque d'écart). Loin des dangers
    # (prox=0), aucun effet : les routes en eau libre ne changent pas.
    with np.errstate(invalid="ignore"):
        shallow_bias = np.where(
            np.isfinite(depth), np.clip((8.0 - depth) / 8.0, 0.0, 1.0), 1.0,
        )
    cost_extra += prox * shallow_bias * 0.5
    # 26/07 (bug Vilaine à marée haute) — les cellules DÉCOUVRANTES (fond
    # < 0,5 m ZH) restent navigables quand la marée les couvre, mais coûtent
    # PLUS CHER : l'A* reste dans le vrai chenal au lieu de couper les
    # vasières (raccourcis de décimation ensuite REFUSÉS par le contrôle
    # pleine résolution → no_route trompeur).
    with np.errstate(invalid="ignore"):
        dry_pen = np.where(
            np.isfinite(depth), np.clip((0.5 - depth) / 2.5, 0.0, 1.0), 0.0,
        )
    cost_extra += dry_pen * 0.9
    # ── 03/08/2026 (RÈGLE 2 du Moteur C — « la profondeur prime sur la
    # distance ») — SURCOÛT « MANQUE DE FOND » GLOBAL, piloté par la
    # contextvar core.nav_rules.DEPTH_PRIORITY. Défaut (0.0, …) → aucun
    # surcoût : les Moteurs A (signalmar.v1) et B (signalmar.v2) sont
    # STRICTEMENT inchangés. Seul le Moteur C (signalmar.v3) l'active.
    _w_depth, _d_ref = DEPTH_PRIORITY.get()
    if _w_depth > 0.0 and _d_ref > 0.0:
        with np.errstate(invalid="ignore"):
            lack = np.where(
                np.isfinite(depth),
                np.clip((_d_ref - depth) / _d_ref, 0.0, 1.0),
                1.0,
            )
        cost_extra += lack * float(_w_depth)
    # 27/07 (consigne armateur vidéo 15h45 : « c'est OBLIGATOIRE de suivre
    # les chenaux ») — ATTRACTION DE PORTE : autour de chaque couple de
    # latérales rouge/verte (= porte de chenal), l'eau NETTEMENT À CÔTÉ de
    # l'axe du chenal (coordonnée transverse |s| > 0,7 × écartement) coûte
    # plus cher → l'A* passe PAR les portes au lieu de couper à côté
    # (raccourci sur la vasière couverte à l'ouest des n°5/6/8 du chenal de
    # Vannes). La bande DANS l'axe (|s| ≤ 0,7 × écartement) reste gratuite :
    # le chenal lui-même n'est jamais pénalisé. Tous modes, dernier recours
    # inclus.
    seamarks_g = get_seamarks()
    if seamarks_g is not None:
        mlng = m_per_deg_lng(lat_mid)
        for (g_lat, g_lng, gap, ux, uy) in seamarks_g.gates(
                float(lats[-1]), float(lats[0]), float(lngs[0]), float(lngs[-1])):
            r_att = max(2.5 * gap, 450.0)
            if r_att < 1.5 * max(cy, cx):
                continue
            ry = int(math.ceil(r_att / cy))
            rx = int(math.ceil(r_att / cx))
            br = int(np.clip(np.searchsorted(-lats, -g_lat), 0, len(lats) - 1))
            bc = int(np.clip(np.searchsorted(lngs, g_lng), 0, len(lngs) - 1))
            r0, r1 = max(0, br - ry), min(len(lats), br + ry + 1)
            c0, c1 = max(0, bc - rx), min(len(lngs), bc + rx + 1)
            if r1 <= r0 or c1 <= c0:
                continue
            dyy = (lats[r0:r1, None] - g_lat) * M_PER_DEG_LAT
            dxx = (lngs[None, c0:c1] - g_lng) * mlng
            dd2 = dxx * dxx + dyy * dyy
            s_cross = np.abs(dxx * ux + dyy * uy)  # écart transverse à l'axe
            ring = (dd2 <= r_att * r_att) & (s_cross > 0.7 * gap)
            cost_extra[r0:r1, c0:c1] += np.where(ring, 0.6, 0.0)

    path = _astar(nav, cost_extra, snap_s, snap_g, cy, cx)
    if path is None:
        # 22/07/2026 (demande armateur) — NE PAS jeter la route : LOCALISER le
        # blocage. Composante atteignable depuis le départ → cellule la plus
        # proche du but = point exact où « ça coince ».
        lab, _n = ndimage.label(nav, structure=np.ones((3, 3), dtype=bool))
        if trap_check:
            # 23/07/2026 (bug armateur : « Passage impossible » depuis un
            # départ posé À TERRE à Locmariaquer) — le snap peut accrocher une
            # POCHE d'eau isolée. Si la composante du départ/de l'arrivée est
            # minuscule, c'est l'EXTRÉMITÉ qui est en cause → _SnapFail
            # (message clair « départ/destination non navigable » + fallback
            # Arradon des comptes de test) au lieu d'un no_route trompeur.
            cell_km2 = (cy * cx) / 1e6
            # 27/07/2026 (vidéo 15h45, end_blocked fantôme à Port Navalo) —
            # le snap peut accrocher une POCHE (lagune isolée à cette marée)
            # alors que l'eau LIBRE est à quelques cellules : on RE-SNAPPE
            # d'abord vers la composante non-piège la plus proche, et on ne
            # refuse sec que si elle n'existe pas dans le rayon du snap.
            sizes = np.bincount(lab.ravel())
            sizes[0] = 0
            big = (sizes * cell_km2 >= TRAP_POCKET_KM2)[lab]

            def _resnap_big(r0i: int, c0i: int) -> Optional[tuple[int, int]]:
                # D'abord le rayon standard, puis élargi (3×) : à marée
                # haute l'estran couvert forme des poches à côté du VRAI
                # chenal (Locmariaquer) — on raccroche l'eau libre voisine.
                got = _snap(nav & big, r0i, c0i, cell_m)
                if got is not None:
                    return got
                rad = int(3 * SNAP_MAX_M / cell_m) + 1
                rr0, rr1 = max(0, r0i - rad), min(nav.shape[0], r0i + rad + 1)
                cc0, cc1 = max(0, c0i - rad), min(nav.shape[1], c0i + rad + 1)
                idx2 = np.argwhere(nav[rr0:rr1, cc0:cc1] & big[rr0:rr1, cc0:cc1])
                if idx2.size == 0:
                    return None
                d2b = (idx2[:, 0] + rr0 - r0i) ** 2 + (idx2[:, 1] + cc0 - c0i) ** 2
                i2 = int(np.argmin(d2b))
                if math.sqrt(float(d2b[i2])) * cell_m > 3 * SNAP_MAX_M:
                    return None
                return (int(idx2[i2, 0] + rr0), int(idx2[i2, 1] + cc0))

            if float(np.count_nonzero(lab == lab[snap_s])) * cell_km2 < TRAP_POCKET_KM2:
                snap_s2 = _resnap_big(rs, cs)
                if snap_s2 is None:
                    raise _SnapFail("start")
                snap_s = snap_s2
            # 22/07/2026 — arrivée déjà DÉPLACÉE (end_snap) : une poche
            # d'arrivée minuscule ne doit plus refuser sec ; on laisse le
            # _LegBlocked livrer la route jusqu'au point atteignable.
            if trap_end and float(np.count_nonzero(lab == lab[snap_g])) * cell_km2 < TRAP_POCKET_KM2:
                snap_g2 = _resnap_big(rg, cg)
                if snap_g2 is None:
                    raise _SnapFail("end")
                snap_g = snap_g2
        comp = lab == lab[snap_s]
        idx = np.argwhere(comp)
        d2 = ((idx[:, 0] - snap_g[0]) * cy) ** 2 + ((idx[:, 1] - snap_g[1]) * cx) ** 2
        i = int(np.argmin(d2))
        dist_m = np.sqrt(d2.astype(np.float64))
        near = np.flatnonzero(dist_m <= dist_m[i] + BLOCKED_DEPTH_TOL_M)
        cand_depth = depth[idx[near, 0], idx[near, 1]]
        finite = np.isfinite(cand_depth)
        if finite.any():
            i = near[finite][int(np.argmax(cand_depth[finite]))]
        best = (int(idx[i, 0]), int(idx[i, 1]))
        blocked_at = (float(lats[best[0]]), float(lngs[best[1]]))
        ppath = _astar(nav, cost_extra, snap_s, best, cy, cx) or [snap_s, best]
        raise _LegBlocked(blocked_at, _to_latlng(lats, lngs, _smooth(nav, ppath)))

    raw = _smooth(nav, path)
    if do_round:
        pts = _round_corners(nav, [(float(r), float(c)) for r, c in raw])
    else:
        pts = [(float(r), float(c)) for r, c in raw]
    return {
        "pts": _to_latlng(lats, lngs, pts),
        "raw": _to_latlng(lats, lngs, raw),
        "step": step,
    }


def _blocked_payload(blocked_at: tuple[float, float], partial_pts: list[tuple[float, float]]) -> dict:
    return {
        "blocked_at": {"lat": round(blocked_at[0], 6), "lng": round(blocked_at[1], 6)},
        "partial_waypoints": [
            {"lat": round(p[0], 6), "lng": round(p[1], 6)} for p in partial_pts
        ],
    }


# ── 22/07/2026 — REDRESSEMENT GLOBAL (lot armateur « écarts injustifiés ») ──
# Après le raffinement, on tend chaque segment en ligne droite tant que le
# COULOIR reste sûr : profondeur PLEINE RÉSOLUTION échantillonnée sur 5
# lignes parallèles (pas ~15 m) + distance minimale aux balises ET dangers
# (roches, épaves, obstructions). Supprime les crochets hérités des passes
# grossière/fine sans jamais couper près d'un danger.

def _sample_step_m(grid: BathyGrid, a: tuple[float, float], b: tuple[float, float]) -> float:
    """Pas d'échantillonnage des contrôles pleine résolution : 15 m en zone
    fine (20 m), 40 m ailleurs (cellules 100 m → ≥ 2.5 échantillons/cellule,
    aucune cellule sautée) — 23/07, perf des routes longues."""
    g0 = grid.grids[0] if hasattr(grid, "grids") else grid
    gw, gs, ge, gn = g0.bounds
    if max(a[1], b[1]) < gw or min(a[1], b[1]) > ge \
            or max(a[0], b[0]) < gs or min(a[0], b[0]) > gn:
        return 40.0
    return 15.0


def _corridor_safe(
    grid: BathyGrid,
    a: tuple[float, float], b: tuple[float, float],
    min_depth: float, lateral_margin_m: float,
    clearance: Optional[np.ndarray],
    half_m: Optional[float] = None,
    gates_arr: Optional[np.ndarray] = None,
    strict_depth_w: Optional[float] = None,
) -> bool:
    """True si le couloir a→b (± ~70 % de la marge latérale, ou ± half_m si
    fourni) reste ≥ min_depth partout ET à distance réglementaire de chaque
    balise/danger.

    28/07 — gates_arr (lat, lng, gap_m, u_est, u_nord) : le couloir ne doit
    pas non plus franchir un MUR DE PORTE de chenal (eau peu profonde hors
    de la porte) — sinon le redressement/l'arrondi recoupaient la vasière
    que l'A* venait d'éviter (contrainte dure, consigne support)."""
    lat_mid = (a[0] + b[0]) / 2
    mlng = m_per_deg_lng(lat_mid)
    dy = (b[0] - a[0]) * M_PER_DEG_LAT   # +nord (m)
    dx = (b[1] - a[1]) * mlng            # +est (m)
    seg_m = math.hypot(dy, dx)
    if seg_m < 1.0:
        return True
    n = max(2, int(seg_m / _sample_step_m(grid, a, b)) + 1)
    t = np.linspace(0.0, 1.0, n)
    lat_c = a[0] + (b[0] - a[0]) * t
    lng_c = a[1] + (b[1] - a[1]) * t
    ux, uy = dx / seg_m, dy / seg_m      # direction unitaire (est, nord)
    px, py = -uy, ux                     # perpendiculaire unitaire
    # 23/07 (« trop proche des côtes ») — demi-couloir MINIMUM 25 m : le
    # redressement ne colle plus la route au ras des cailloux quand la marge
    # latérale utilisateur est petite (10 m).
    half = max(25.0, 0.7 * lateral_margin_m) if half_m is None else half_m
    offsets = (-half, -half / 2, 0.0, half / 2, half) if half > 0 else (0.0,)
    lats_s: list[np.ndarray] = []
    lngs_s: list[np.ndarray] = []
    for off in offsets:
        lats_s.append(lat_c + (py * off) / M_PER_DEG_LAT)
        lngs_s.append(lng_c + (px * off) / mlng)
    la = np.concatenate(lats_s)
    lo = np.concatenate(lngs_s)
    # 22/07 (multi-zones) — échantillonnage pleine résolution via la grille
    # (mosaïque : la grille la plus fine répond, NaN = terre/hors données).
    depths = grid.sample(la, lo)
    if not np.isfinite(depths).all() or (depths < min_depth).any():
        return False
    # 28/07 — MURS DE PORTE (contrainte dure de chenal) : aucun échantillon
    # du couloir en eau PEU PROFONDE (fond carte < strict_depth_w) dans la
    # bande du mur (|t| ≤ w_half le long de la ligne de porte, 0,7×gap <
    # |s| ≤ r_wall). Mêmes règles que le masque A* (_nav_for).
    if gates_arr is not None and len(gates_arr) and strict_depth_w is not None:
        mid_lat, mid_lng_pt = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        d_gate = np.hypot((gates_arr[:, 0] - mid_lat) * M_PER_DEG_LAT,
                          (gates_arr[:, 1] - mid_lng_pt) * mlng)
        near = gates_arr[d_gate <= seg_m / 2 + 1200.0]
        for g_lat, g_lng, gap, gux, guy in near:
            r_wall = max(2.5 * gap, 450.0)
            w_half = max(0.5 * gap, 30.0)
            dxg = (lo - g_lng) * mlng
            dyg = (la - g_lat) * M_PER_DEG_LAT
            s = dxg * gux + dyg * guy
            t_ = dyg * gux - dxg * guy
            bad = ((np.abs(t_) <= w_half) & (np.abs(s) > 0.7 * gap)
                   & (np.abs(s) <= r_wall) & (depths < strict_depth_w))
            if bad.any():
                return False
    if clearance is not None and len(clearance):
        mx = (clearance[:, 1] - a[1]) * mlng
        my = (clearance[:, 0] - a[0]) * M_PER_DEG_LAT
        tp = np.clip((mx * dx + my * dy) / (seg_m * seg_m), 0.0, 1.0)
        dist = np.hypot(mx - tp * dx, my - tp * dy)
        if (dist < clearance[:, 2]).any():
            return False
    return True


def _straighten(
    grid: BathyGrid, pts: list[tuple[float, float]],
    min_depth: float, lateral_margin_m: float, clearance: Optional[np.ndarray],
    gates_arr: Optional[np.ndarray] = None,
    strict_depth_w: Optional[float] = None,
) -> list[tuple[float, float]]:
    """String pulling GLOBAL sur le tracé final (couloir pleine résolution).
    23/07 : raccourcis bornés à 30 km (au-delà, coût O(n²) prohibitif sur les
    routes de 200+ km pour un gain de tracé négligeable)."""
    if len(pts) <= 2:
        return pts
    cum = [0.0]
    for k in range(len(pts) - 1):
        cum.append(cum[-1] + math.hypot(
            (pts[k + 1][0] - pts[k][0]) * M_PER_DEG_LAT,
            (pts[k + 1][1] - pts[k][1]) * m_per_deg_lng(pts[k][0])))
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and cum[j] - cum[i] > 30_000.0:
            j -= 1
        while j > i + 1 and not _corridor_safe(grid, pts[i], pts[j], min_depth, lateral_margin_m, clearance,
                                               gates_arr=gates_arr, strict_depth_w=strict_depth_w):
            j -= 1
        out.append(pts[j])
        i = j
    return out


def _centerline_min(grid: BathyGrid, pts: list[tuple[float, float]]) -> float:
    """Fond minimal (m) le long de la polyligne, pas ~15 m ; NaN (terre/île)
    → -999 (pire). Sert à départager les candidats de réparation."""
    worst = float("inf")
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg_m = math.hypot((b[0] - a[0]) * M_PER_DEG_LAT,
                           (b[1] - a[1]) * m_per_deg_lng(a[0]))
        n = max(2, int(seg_m / _sample_step_m(grid, a, b)) + 1)
        t = np.linspace(0.0, 1.0, n)
        la = a[0] + (b[0] - a[0]) * t
        lo = a[1] + (b[1] - a[1]) * t
        d = grid.sample(la, lo)
        if np.isnan(d).any():
            return -999.0
        worst = min(worst, float(d.min()))
    return worst


def _clearance_worst_ratio(
    pts: list[tuple[float, float]], clearance: Optional[np.ndarray],
) -> float:
    """Pire ratio écart/consigne du tracé face aux cercles d'écart (1.0 =
    toutes les consignes respectées). 11/08 soir (Moteur E) : départage les
    candidats de réparation à pénalité de côté égale — cf. _repair_segments."""
    if clearance is None or not len(clearance) or len(pts) < 2:
        return 1.0
    mlng = m_per_deg_lng(pts[0][0])
    P = np.asarray(pts, dtype=np.float64)
    ax = (P[:-1, 1][None, :] - clearance[:, 1][:, None]) * mlng
    ay = (P[:-1, 0][None, :] - clearance[:, 0][:, None]) * M_PER_DEG_LAT
    bx = (P[1:, 1][None, :] - clearance[:, 1][:, None]) * mlng
    by = (P[1:, 0][None, :] - clearance[:, 0][:, None]) * M_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.clip(-(ax * dx + ay * dy) / np.where(L2 > 0, L2, 1.0), 0.0, 1.0)
    d = np.hypot(ax + t * dx, ay + t * dy).min(axis=1)
    return float(np.minimum(d / np.maximum(clearance[:, 2], 1.0), 1.0).min())


def _wrong_side_penalty_m(
    pts: list[tuple[float, float]],
    exempt: Optional[tuple] = None,
) -> float:
    """11/08 soir (Moteur E — bug Logoden) : PÉNALITÉ « mauvais côté » d'un
    tracé = somme des profondeurs de violation (influence − distance) sur
    les latérales à direction FIABLE, mêmes règles que l'audit du Moteur D
    (influence 200 m, plafonnée à 0,8 × l'écartement du couple, exemption
    200 m autour du départ/de l'arrivée). 0.0 = aucun mauvais côté. Sert à
    comparer un candidat de réparation IMPARFAIT à l'original : mieux vaut
    frôler un cercle d'écart du BON côté que passer du MAUVAIS côté."""
    sm = get_seamarks()
    if sm is None or len(pts) < 2:
        return 0.0
    la = [p[0] for p in pts]
    lo = [p[1] for p in pts]
    mlng = m_per_deg_lng((min(la) + max(la)) / 2)
    P = np.asarray(pts, dtype=np.float64)
    tot = 0.0
    for m in sm.marks:
        if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
            continue
        if not (min(la) - 0.01 <= m["lat"] <= max(la) + 0.01
                and min(lo) - 0.01 <= m["lng"] <= max(lo) + 0.01):
            continue
        if exempt and any(
            math.hypot((m["lat"] - q[0]) * M_PER_DEG_LAT,
                       (m["lng"] - q[1]) * mlng) < 200.0
            for q in exempt
        ):
            continue
        d_dir = sm.mark_dir_confident(m)
        if d_dir is None:
            continue
        de, dn = d_dir
        u = (dn, -de) if m["category"] == "port" else (-dn, de)
        influence = 200.0
        pair = sm._pair_of(m)
        if pair is not None:
            gap = math.hypot((pair["lat"] - m["lat"]) * M_PER_DEG_LAT,
                             (pair["lng"] - m["lng"]) * mlng)
            influence = min(influence, max(0.8 * gap, 40.0))
        ax = (P[:-1, 1] - m["lng"]) * mlng
        ay = (P[:-1, 0] - m["lat"]) * M_PER_DEG_LAT
        bx = (P[1:, 1] - m["lng"]) * mlng
        by = (P[1:, 0] - m["lat"]) * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        with np.errstate(invalid="ignore", divide="ignore"):
            t = np.clip(-(ax * dx + ay * dy) / np.where(L2 > 0, L2, 1.0), 0.0, 1.0)
        px, py = ax + t * dx, ay + t * dy
        dists = np.hypot(px, py)
        k = int(np.argmin(dists))
        d = float(dists[k])
        if d > influence:
            continue
        if px[k] * u[0] + py[k] * u[1] > 0.0:
            continue  # bon côté
        tot += influence - d
    return tot


def _repair_segments(
    grid: BathyGrid, pts: list[tuple[float, float]],
    min_depth: float, lateral_margin_m: float, clearance: Optional[np.ndarray],
    strict_depth: Optional[float] = None,
    strict_exempt: Optional[tuple] = None,
    depth_rec: int = 0,
    gates_arr: Optional[np.ndarray] = None,
) -> list[tuple[float, float]]:
    """22/07/2026 (lot armateur « roche semi-couvrante ») — CONTRÔLE FINAL en
    pleine résolution : tout segment dont la LIGNE CENTRALE croise un fond
    < seuil ou passe trop près d'un danger est RE-RÉSOLU en fenêtre fine
    (step≈1). Les fenêtres grossières max-poolées peuvent rater une tête de
    roche < 60 m : ce filet de sécurité l'attrape.

    23/07 (extension de zone) — le REMPLACEMENT est lui-même RE-VALIDÉ (un
    long tronçon re-résolu peut encore être poolé) et réparé RÉCURSIVEMENT
    (≤ 2 niveaux) ; 2 fenêtres essayées (serrée puis élargie ~3 km : détour
    de plateau côtier type Penmarc'h). Ce qui reste inréparable est tranché
    par le REFUS FERME en fin de compute_route."""
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        a = out[-1]
        if _corridor_safe(grid, a, pts[i + 1], min_depth, lateral_margin_m, clearance, half_m=15.0,
                          gates_arr=gates_arr, strict_depth_w=strict_depth):
            out.append(pts[i + 1])
            i += 1
            continue
        # 23/07 — FUSION des tronçons consécutifs dangereux : réparer
        # waypoint par waypoint ne peut pas restructurer un passage qui
        # traverse tout un plateau rocheux (Penmarc'h) — on re-résout d'un
        # bloc du dernier point sûr au prochain point sûr.
        j = i + 1
        while j < len(pts) - 1 and not _corridor_safe(
            grid, pts[j], pts[j + 1], min_depth, lateral_margin_m, clearance, half_m=15.0,
            gates_arr=gates_arr, strict_depth_w=strict_depth,
        ):
            j += 1
        b = pts[j]
        fixed = False
        best_cand: Optional[list[tuple[float, float]]] = None
        best_min = _centerline_min(grid, [a] + pts[i + 1:j + 1])  # à battre : l'original
        # 11/08 soir (Moteur E — bug Logoden) : quand AUCUN candidat n'est
        # parfait, l'original était conservé même s'il passait du MAUVAIS
        # côté du balisage (route à 71 m au NORD de Logoden alors qu'un
        # tracé au SUD, du bon côté, existait à un frôlement d'écart près).
        # Sous SIDE_ABSOLUTE, on retient le candidat qui RÉDUIT la pénalité
        # de mauvais côté sans passer sous le seuil de profondeur (départage
        # par le respect des écarts). Moteurs gelés (A/B/C/D) : inchangés.
        orig_min = best_min
        side_mode = SIDE_ABSOLUTE.get()
        orig_pen = (_wrong_side_penalty_m([a] + pts[i + 1:j + 1], strict_exempt)
                    if side_mode else 0.0)
        best_pen = orig_pen
        best_pen_ratio = -1.0
        best_pen_cand: Optional[list[tuple[float, float]]] = None
        # px dimensionné pour STEP 1 sur la grille de base 100 m (fenêtre
        # poolée = snap/chemin sur des cellules « max » qui peuvent être des
        # roches en pleine résolution → candidats jamais validables, Raz de
        # Sein). Plafond 2400 px ; au-delà la récursion découpe.
        span_deg = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        for pad in (0.008, 0.03, 0.08, 0.25):
            # 0.25° (~28 km) : le détour peut être un DOGLEG hors de la bbox
            # du span (contourner la pointe du Raz pour franchir le Raz de
            # Sein). Tenté en dernier (fenêtre large = plus lent).
            px = min(2400, max(700, int((span_deg + 2 * pad + 0.02) / 0.001) + 50))
            try:
                leg = _solve_leg(
                    grid, a, b, min_depth, lateral_margin_m,
                    max_px=px, pad_min=pad, do_round=False, strict_depth=strict_depth,
                    strict_exempt=strict_exempt, pad_frac=0.05,
                )["raw"]
            except Exception:
                continue
            if depth_rec < 1:
                leg = _repair_segments(
                    grid, leg, min_depth, lateral_margin_m, clearance,
                    strict_depth, strict_exempt, depth_rec + 1,
                    gates_arr=gates_arr,
                )
            # 23/07 — la JOINTURE a→snap(a) fait partie du candidat : le snap
            # de _solve_leg peut décaler le départ du tronçon de ≤ 400 m, et
            # ce petit raccord doit être contrôlé comme le reste.
            if i == 0:
                cand = leg  # le départ de route peut suivre le snap (≤ 400 m)
            elif abs(leg[0][0] - a[0]) + abs(leg[0][1] - a[1]) > 1e-9:
                cand = [a] + leg
            else:
                cand = [a] + leg[1:]
            if all(
                _corridor_safe(grid, cand[k], cand[k + 1], min_depth,
                               lateral_margin_m, clearance, half_m=15.0,
                               gates_arr=gates_arr, strict_depth_w=strict_depth)
                for k in range(len(cand) - 1)
            ):
                if i == 0:
                    out[0] = cand[0]  # départ ajusté au snap fin (≤ 400 m)
                out.extend(cand[1:])
                fixed = True
                break
            cand_min = _centerline_min(grid, cand)
            if cand_min > best_min:  # pas parfait mais PLUS PROFOND que l'original
                best_min, best_cand = cand_min, cand
            if (side_mode and orig_pen > 1.0
                    and cand_min >= min(orig_min, min_depth)):
                pen = _wrong_side_penalty_m(cand, strict_exempt)
                if pen < orig_pen - 1.0:
                    ratio = _clearance_worst_ratio(cand, clearance)
                    if (pen < best_pen - 1.0
                            or (pen < orig_pen - 1.0 and abs(pen - best_pen) <= 1.0
                                and ratio > best_pen_ratio)):
                        best_pen, best_pen_ratio = pen, ratio
                        best_pen_cand = cand
        if not fixed:
            if best_pen_cand is not None:
                # Moteur E : le candidat passe du BON côté du balisage
                # (pénalité de côté réduite) — retenu malgré un écart imparfait.
                if i == 0:
                    out[0] = best_pen_cand[0]
                out.extend(best_pen_cand[1:])
            elif best_cand is not None:
                if i == 0:
                    out[0] = best_cand[0]
                out.extend(best_cand[1:])
            else:
                out.extend(pts[i + 1:j + 1])
        i = j
    return out


def nearest_navigable(
    lat: float, lng: float, min_depth: float, max_m: float = 5000.0,
) -> Optional[tuple[float, float]]:
    """Point d'eau NAVIGABLE le plus proche (≤ max_m), pleine résolution.
    23/07 — fallback des comptes de test : un départ posé à terre repart de
    l'eau la plus proche (Arradon seulement si aucune eau à moins de max_m)."""
    grid = get_grid()
    if grid is None:
        return None
    dd = max_m / M_PER_DEG_LAT
    win = grid.window(lng - dd * 1.6, lat - dd, lng + dd * 1.6, lat + dd, max_px=700)
    if win is None:
        return None
    depth, lngs, lats, _step = win
    ok = np.isfinite(depth) & (depth >= min_depth)
    if not ok.any():
        return None
    rr, cc = np.nonzero(ok)
    d2 = ((lats[rr] - lat) * M_PER_DEG_LAT) ** 2 + ((lngs[cc] - lng) * m_per_deg_lng(lat)) ** 2
    i = int(np.argmin(d2))
    if d2[i] > max_m ** 2:
        return None
    return float(lats[rr[i]]), float(lngs[cc[i]])


def nearest_reachable(
    start: tuple[float, float], end: tuple[float, float],
    min_depth: float, lateral_margin_m: float, strict_depth: Optional[float],
    max_m: float,
    prefer_depth: Optional[float] = None,
) -> Optional[tuple[float, float]]:
    """Point navigable le plus proche de ``end`` ATTEIGNABLE depuis ``start``
    (même composante d'eau, fenêtre grossière poolée). 22/07/2026 — évite
    d'accrocher l'arrivée dans une POCHE fermée (bassin de marina isolé dans
    le MNT, mare d'estran) : l'eau la plus proche N'EST pas toujours la bonne.
    None si aucune cellule de la composante du départ à moins de max_m."""
    grid = get_grid()
    if grid is None:
        return None
    try:
        # Fenêtre LARGE (mêmes marges que la dernière escalade de la passe 1) :
        # le chemin vers l'eau proche de la destination peut exiger un grand
        # détour hors bbox (sortie du Golfe par Port-Navalo).
        depth, lngs, lats, _step = _window_for(
            grid, start, end, max_px=MAX_DIM, pad_min=0.40, pool=True, pad_frac=2.5,
        )
    except RouteError:
        return None
    lat_mid = float((lats[0] + lats[-1]) / 2)
    cy = abs(float(lats[1] - lats[0])) * M_PER_DEG_LAT if len(lats) > 1 else abs(grid.dy) * M_PER_DEG_LAT
    cx = abs(float(lngs[1] - lngs[0])) * m_per_deg_lng(lat_mid) if len(lngs) > 1 else grid.dx * m_per_deg_lng(lat_mid)
    nav = _nav_for(depth, lats, lngs, min_depth, lateral_margin_m, cy, cx, lat_mid,
                   strict_depth, (start, end))
    rs, cs = _cell_of(lats, lngs, *start)
    snap_s = _snap(nav, rs, cs, min(cy, cx), depth)
    if snap_s is None:
        return None
    lab, _n = ndimage.label(nav, structure=np.ones((3, 3), dtype=bool))
    comp = lab == lab[snap_s]
    idx = np.argwhere(comp)
    d2 = (((lats[idx[:, 0]] - end[0]) * M_PER_DEG_LAT) ** 2
          + ((lngs[idx[:, 1]] - end[1]) * m_per_deg_lng(lat_mid)) ** 2)
    # 26/07 (bug Vilaine « Foireuse 3 ») — la fenêtre POOLÉE est optimiste :
    # la cellule la plus proche peut retomber À TERRE en pleine résolution
    # (max-pooling terre+chenal). On parcourt les candidats par distance
    # croissante et on VALIDE chacun sur la grille pleine résolution.
    order = np.argsort(d2)
    # Candidat le plus proche navigable À LA MARÉE DU CALCUL (comportement
    # historique) — sert de référence de distance.
    cand0: Optional[tuple[float, float]] = None
    d0 = None
    for k in order[:200]:
        if d2[k] > max_m ** 2:
            break
        cand = (float(lats[idx[k, 0]]), float(lngs[idx[k, 1]]))
        d_full = grid.depth_at(cand[0], cand[1])
        if d_full is not None and d_full >= min_depth:
            cand0, d0 = cand, math.sqrt(float(d2[k]))
            break
        # Centre de cellule poolée à terre : un point navigable pleine
        # résolution existe peut-être à ≤ 400 m (le chenal qui a « gagné »
        # le pooling) — on l'accroche directement.
        snapped = _snap_fullres(grid, cand[0], cand[1], min_depth)
        if snapped is not None:
            cand0, d0 = snapped, math.sqrt(float(d2[k]))
            break
    if cand0 is None:
        return None
    # 27/07 (bug armateur vidéo, « arrivée en plein sur la vasière ») — le
    # plus proche géométrique peut tomber sur un ESTRAN momentanément couvert
    # (vasière à marée haute) au lieu du chenal voisin. Corrections :
    # 27/07 (bug armateur vidéo, « arrivée en plein sur la vasière ») — parmi
    # les candidats proches (≤ +400 m du plus proche), on prend le plus
    # PROFOND avec un léger malus de distance : l'arrivée tombe dans le
    # THALWEG (lit du chenal), jamais sur l'estran voisin momentanément
    # couvert. (Une préférence « toujours en eau » plus large a été essayée
    # puis retirée : elle tirait l'arrivée des rivières — Vilaine — des
    # centaines de mètres en aval, retest iter115.)
    if prefer_depth is not None and prefer_depth > min_depth:
        best_cand = cand0
        best_score = None
        bd = grid.depth_at(*cand0)
        if bd is not None:
            best_score = bd
        for k in order[:400]:
            if d2[k] > (d0 + 400.0) ** 2 or d2[k] > max_m ** 2:
                break
            cand = (float(lats[idx[k, 0]]), float(lngs[idx[k, 1]]))
            d_full = grid.depth_at(cand[0], cand[1])
            if d_full is None or d_full < min_depth:
                continue
            score = min(d_full, prefer_depth + 0.5) \
                - (math.sqrt(float(d2[k])) - d0) / 800.0
            if best_score is None or score > best_score:
                best_cand, best_score = cand, score
        return best_cand
    return cand0


def _snap_fullres(
    grid: BathyGrid, lat: float, lng: float, min_depth: float,
) -> Optional[tuple[float, float]]:
    """Cellule PLEINE résolution la plus proche avec assez d'eau (≤ SNAP_MAX_M).
    Utilisé pour les extrémités : le snap des passes décimées peut retomber
    sur un estran (cellule poolée « profonde » dont le centre assèche)."""
    win = grid.window(lng - 0.007, lat - 0.005, lng + 0.007, lat + 0.005, max_px=800)
    if win is None:
        return None
    depth, lngs, lats, _step = win
    ok = np.isfinite(depth) & (depth >= min_depth)
    if not ok.any():
        return None
    r = int(np.clip(np.searchsorted(-lats, -lat), 0, len(lats) - 1))
    c = int(np.clip(np.searchsorted(lngs, lng), 0, len(lngs) - 1))
    cy = abs(float(lats[1] - lats[0])) * M_PER_DEG_LAT if len(lats) > 1 else 20.0
    cx = abs(float(lngs[1] - lngs[0])) * m_per_deg_lng(lat) if len(lngs) > 1 else 20.0
    idx = np.argwhere(ok)
    d2 = ((idx[:, 0] - r) * cy) ** 2 + ((idx[:, 1] - c) * cx) ** 2
    i = int(np.argmin(d2))
    if math.sqrt(float(d2[i])) > SNAP_MAX_M:
        return None
    return float(lats[idx[i, 0]]), float(lngs[idx[i, 1]])


FILLET_M = 80.0  # 22/07 v2 (retour armateur) — la courbe débute/finit à ~80 m du waypoint


def _round_pts(
    grid: BathyGrid, pts: list[tuple[float, float]],
    min_depth: float, lateral_margin_m: float, clearance: Optional[np.ndarray],
    gates_arr: Optional[np.ndarray] = None,
    strict_depth_w: Optional[float] = None,
) -> list[tuple[float, float]]:
    """22/07 v2 (retour armateur) — fini les grandes courbes de Chaikin :
    ANGLE DOUX localisé au passage du waypoint. La courbe débute ~80 m avant
    le waypoint et se termine ~80 m après ; entre les waypoints la route
    reste en LIGNE DROITE (le barreur tient un cap constant, pas une courbe).
    Chaque coupe est validée par le couloir sûr (sinon l'angle est gardé)."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[i], pts[i + 1]
        mlng = m_per_deg_lng(b[0])
        d_ab = math.hypot((b[0] - a[0]) * M_PER_DEG_LAT, (b[1] - a[1]) * mlng)
        d_bc = math.hypot((c[0] - b[0]) * M_PER_DEG_LAT, (c[1] - b[1]) * mlng)
        cut1 = min(FILLET_M, 0.4 * d_ab)
        cut2 = min(FILLET_M, 0.4 * d_bc)
        if cut1 < 15.0 or cut2 < 15.0 or d_ab < 1.0 or d_bc < 1.0:
            out.append(b)
            continue
        t1 = 1.0 - cut1 / d_ab
        b1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
        t2 = cut2 / d_bc
        b2 = (b[0] + (c[0] - b[0]) * t2, b[1] + (c[1] - b[1]) * t2)
        # Point intermédiaire tiré à mi-chemin vers le waypoint : l'angle est
        # cassé en DEUX petits changements de cap (≈ moitié de l'angle chacun).
        m = ((b1[0] + b2[0]) / 2 + b[0]) / 2, ((b1[1] + b2[1]) / 2 + b[1]) / 2
        if (_corridor_safe(grid, b1, m, min_depth, lateral_margin_m, clearance,
                           gates_arr=gates_arr, strict_depth_w=strict_depth_w)
                and _corridor_safe(grid, m, b2, min_depth, lateral_margin_m, clearance,
                                   gates_arr=gates_arr, strict_depth_w=strict_depth_w)):
            out.extend([b1, m, b2])
        else:
            out.append(b)
    out.append(pts[-1])
    return out


# ── 22/07/2026 — CORRIDOR DE NAVIGATION DYNAMIQUE (GO armateur) ────────────
# Demi-largeur SÛRE du corridor d'alerte d'écart pour CHAQUE segment :
# 150 m en eaux libres, resserrée automatiquement près des obstacles,
# PLANCHER 40 m (précision GPS ~5-10 m + embardées de barre : en dessous
# l'alarme sonnerait sans arrêt et finirait ignorée).
CORRIDOR_WIDTHS = (150.0, 120.0, 90.0, 60.0, 40.0)


def _corridors_for(
    grid: Optional[BathyGrid], waypoints: list[dict],
    min_depth: float, lateral_margin_m: float, clearance: Optional[np.ndarray],
) -> list[float]:
    out: list[float] = []
    for i in range(len(waypoints) - 1):
        a = (waypoints[i]["lat"], waypoints[i]["lng"])
        b = (waypoints[i + 1]["lat"], waypoints[i + 1]["lng"])
        if grid is None or not (grid.covers(*a) and grid.covers(*b)):
            out.append(CORRIDOR_WIDTHS[0])  # hors données → défaut eaux libres
            continue
        w = CORRIDOR_WIDTHS[-1]
        for width in CORRIDOR_WIDTHS:
            if _corridor_safe(grid, a, b, min_depth, lateral_margin_m, clearance, half_m=width):
                w = width
                break
        out.append(w)
    # Transitions DOUCES : un segment ne dépasse jamais son voisin de +30 m
    # (le corridor se resserre progressivement à l'approche d'une zone).
    for _ in range(3):
        for i in range(len(out)):
            neigh = [out[j] for j in (i - 1, i + 1) if 0 <= j < len(out)]
            if neigh:
                out[i] = min(out[i], min(neigh) + 30.0)
    return [round(w) for w in out]


MSG_BLOCKED = (
    "Passage impossible avec ces réglages (tirant d'eau + marges) : "
    "le point de blocage est affiché sur la carte."
)


def _result_for(grid: Optional[BathyGrid], waypoints: list[dict], min_depth: float) -> dict:
    """Distance + profil de profondeur (grille PLEINE résolution) + alertes."""
    lat_mid = sum(w["lat"] for w in waypoints) / len(waypoints)
    profile: list[dict] = []
    total_m = 0.0
    min_seen: Optional[float] = None
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        seg_m = math.hypot(
            (b["lat"] - a["lat"]) * M_PER_DEG_LAT,
            (b["lng"] - a["lng"]) * m_per_deg_lng(lat_mid),
        )
        n = max(1, int(seg_m / PROFILE_STEP_M))
        for k in range(n):
            t = k / n
            lat = a["lat"] + (b["lat"] - a["lat"]) * t
            lng = a["lng"] + (b["lng"] - a["lng"]) * t
            d = grid.depth_at(lat, lng) if grid is not None else None
            dist = total_m + seg_m * t
            profile.append({
                "d_m": round(dist, 1),
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "depth_m": None if d is None else round(float(d), 2),
            })
            if d is not None:
                min_seen = d if min_seen is None else min(min_seen, d)
        total_m += seg_m
    end = waypoints[-1]
    end_d = grid.depth_at(end["lat"], end["lng"]) if grid is not None else None
    profile.append({
        "d_m": round(total_m, 1),
        "lat": end["lat"],
        "lng": end["lng"],
        "depth_m": None if end_d is None else round(float(end_d), 2),
    })
    if end_d is not None:
        min_seen = end_d if min_seen is None else min(min_seen, end_d)

    warnings: list[str] = []
    if min_seen is not None and min_seen < min_depth:
        warnings.append(
            f"Passage à {min_seen:.1f} m de fond (seuil {min_depth:.1f} m) — prudence."
        )

    return {
        "waypoints": waypoints,
        "distance_m": round(total_m, 1),
        "min_depth_m": None if min_seen is None else round(float(min_seen), 2),
        "threshold_m": round(min_depth, 2),
        "depth_profile": profile,
        "warnings": warnings,
        "disclaimer": (
            "Aide à la navigation — profondeurs SHOM au zéro hydrographique "
            "(marée basse, sans marée). Ne remplace pas les cartes officielles "
            "ni la vigilance du barreur."
        ),
    }


def _crosses_farm(waypoints: list[dict]) -> bool:
    """True si le tracé traverse un disque de parc de culture marine."""
    sm = get_seamarks()
    if sm is None or not len(sm.farm_circles) or len(waypoints) < 2:
        return False
    la = [w["lat"] for w in waypoints]
    lo = [w["lng"] for w in waypoints]
    fc = sm.farm_circles
    sel = ((fc[:, 0] >= min(la) - 0.01) & (fc[:, 0] <= max(la) + 0.01)
           & (fc[:, 1] >= min(lo) - 0.01) & (fc[:, 1] <= max(lo) + 0.01))
    fc = fc[sel]
    if not len(fc):
        return False
    mlng = m_per_deg_lng((min(la) + max(la)) / 2)
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        seg_m = math.hypot((b["lat"] - a["lat"]) * M_PER_DEG_LAT,
                           (b["lng"] - a["lng"]) * mlng)
        n = max(2, int(seg_m / 20.0) + 1)
        tt = np.linspace(0.0, 1.0, n + 1)
        s_lat = a["lat"] + (b["lat"] - a["lat"]) * tt
        s_lng = a["lng"] + (b["lng"] - a["lng"]) * tt
        dy = (s_lat[:, None] - fc[None, :, 0]) * M_PER_DEG_LAT
        dx = (s_lng[:, None] - fc[None, :, 1]) * mlng
        # marge -12 m : on signale la traversée FRANCHE (pas l'effleurement
        # de la garde extérieure du semis de disques).
        if bool((dy * dy + dx * dx <= (fc[None, :, 2] - 12.0) ** 2).any()):
            return True
    return False


def _mark_pass_audit(
    waypoints: list[dict], exempt_pts: tuple,
) -> list[str]:
    """27/07 (vidéo 15h45 : Holavre à 11 m) — AUDIT FINAL : si le tracé
    passe plus près d'une balise que son écart minimal (hors abords du
    départ/arrivée DEMANDÉS), on avertit NOMINATIVEMENT au lieu de laisser
    passer en silence (réparation impossible gardée telle quelle)."""
    sm = get_seamarks()
    if sm is None or len(waypoints) < 2:
        return []
    la = [w["lat"] for w in waypoints]
    lo = [w["lng"] for w in waypoints]
    lat_mid = (min(la) + max(la)) / 2
    mlng = m_per_deg_lng(lat_mid)
    out: list[str] = []
    for (m_lat, m_lng, r_std, name) in sm.standoff_circles(
            min(la) - 0.005, max(la) + 0.005, min(lo) - 0.005, max(lo) + 0.005):
        if any(math.hypot((m_lat - p[0]) * M_PER_DEG_LAT, (m_lng - p[1]) * mlng) < 200.0
               for p in exempt_pts):
            continue
        best = float("inf")
        for i in range(len(waypoints) - 1):
            ax = (waypoints[i]["lng"] - m_lng) * mlng
            ay = (waypoints[i]["lat"] - m_lat) * M_PER_DEG_LAT
            bx = (waypoints[i + 1]["lng"] - m_lng) * mlng
            by = (waypoints[i + 1]["lat"] - m_lat) * M_PER_DEG_LAT
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 <= 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / L2))
            best = min(best, math.hypot(ax + t * dx, ay + t * dy))
        if best < r_std - 5.0:
            out.append(
                f"⚠ La route passe à ~{best:.0f} m de la balise « {name} » "
                f"(écart recommandé {r_std:.0f} m) — vérifiez le passage À VUE."
            )
    return out[:4]


def compute_route(
    start_lat: float, start_lng: float,
    end_lat: float, end_lng: float,
    draft_m: float, depth_margin_m: float, lateral_margin_m: float,
    tide_m: float = 0.0,
    _strict_retry: bool = False,
) -> dict:
    """Route automatique en DEUX PASSES (22/07/2026) :
    1. passe GROSSIÈRE sur toute la zone (max-pooling : connectivité fiable) ;
    2. RAFFINEMENT tronçon par tronçon en pleine/haute résolution.
    En cas de blocage : RouteError('no_route') avec payload {blocked_at,
    partial_waypoints} — le front affiche le point de blocage SANS effacer
    la route existante.

    tide_m (22/07, GO armateur) : hauteur d'eau ≈ au-dessus du ZH intégrée au
    calcul — le seuil CARTE devient draft + marge - marée (peut être négatif :
    zones découvrantes couvertes à cette hauteur d'eau). Les ROCHES et les
    épaves dangereuses restent évitées QUELLE QUE SOIT la marée."""
    grid = get_grid()
    if grid is None:
        raise RouteError("no_data", "Bathymétrie non disponible sur ce serveur.")

    draft_m = float(np.clip(draft_m, DRAFT_MIN, DRAFT_MAX))
    depth_margin_m = float(np.clip(depth_margin_m, DEPTH_MARGIN_MIN, DEPTH_MARGIN_MAX))
    lateral_margin_m = float(np.clip(lateral_margin_m, LATERAL_MIN, LATERAL_MAX))
    tide_m = float(np.clip(tide_m, -2.0, 6.0))
    # 23/07/2026 (bug armateur « route sur l'estran ») — PLANCHER −2,5 m :
    # la marée peut ouvrir les petits fonds et les chenaux découvrants
    # ENTRETENUS (chenal de Vannes ≈ −1 à −2,2 m), mais JAMAIS les hautes
    # vasières ni les franges d'îlots (< −2,5 m au ZH). L'ancien plancher
    # −3 m, combiné au balisage non strict, envoyait des routes sur les bancs.
    min_depth = max(draft_m + depth_margin_m - tide_m, -2.5)
    # 27/07 — besoin de fond SANS marée (préférence d'arrivée déplacée).
    base_need = draft_m + depth_margin_m
    # 23/07/2026 (règle armateur) — zone PEU PROFONDE = fond < tirant d'eau +
    # marge + 2 m (SANS marée) : le balisage latéral y est respecté
    # scrupuleusement (mauvais côté interdit au large). En eaux profondes,
    # l'écart standard suffit (passage Teignouse validé terrain). Les abords
    # immédiats du départ/de l'arrivée (< 500 m) restent manœuvrables.
    strict_depth = draft_m + depth_margin_m + 2.0
    # Extrémités DEMANDÉES (avant toute relocalisation) — nécessaires au
    # retry « marge renforcée » du contrôle final (26/07).
    orig_end = (end_lat, end_lng)

    for name, lat, lng in (("départ", start_lat, start_lng), ("arrivée", end_lat, end_lng)):
        if not grid.covers(lat, lng):
            raise RouteError(
                "out_of_coverage",
                f"Point de {name} hors zone couverte (façade Ouest : Manche Ouest → Pertuis charentais).",
            )

    # 22/07/2026 (bug armateur « je ne peux faire aucune route ») —
    # DESTINATION sur l'estran / zone découvrante (plage de Damgan, tourelle
    # de Penvins… à marée basse) : au lieu de refuser, l'arrivée est DÉPLACÉE
    # vers l'eau navigable la plus proche (≤ END_SNAP_MAX_M) et la route
    # l'annonce clairement. Le refus sec (end_blocked) ne reste que s'il n'y
    # a AUCUNE eau navigable à moins de 3 km.
    end_snap: Optional[dict] = None
    d_end0 = grid.depth_at(end_lat, end_lng)
    if d_end0 is None or d_end0 < min_depth:
        # D'abord l'eau ATTEIGNABLE depuis le départ (évite les poches
        # fermées : bassin de marina isolé dans le MNT, mare d'estran) ;
        # à défaut, l'eau navigable la plus proche.
        near_end = nearest_reachable(
            (start_lat, start_lng), (end_lat, end_lng),
            min_depth, lateral_margin_m, strict_depth, END_SNAP_MAX_M,
            prefer_depth=base_need,
        ) or nearest_navigable(
            end_lat, end_lng, max(min_depth, base_need), END_SNAP_MAX_M,
        ) or nearest_navigable(end_lat, end_lng, min_depth, END_SNAP_MAX_M)
        if near_end is not None:
            off_m = math.hypot(
                (near_end[0] - end_lat) * M_PER_DEG_LAT,
                (near_end[1] - end_lng) * m_per_deg_lng(end_lat),
            )
            end_snap = {
                "requested": {"lat": round(end_lat, 6), "lng": round(end_lng, 6)},
                "offset_m": round(off_m),
            }
            end_lat, end_lng = near_end

    a = (start_lat, start_lng)
    b = (end_lat, end_lng)
    # 27/07 (bug armateur vidéo : route SUR la balise No8) — les EXEMPTIONS
    # de proximité (écart minimal aux balises, mouillages, balisage strict)
    # s'appliquent aux points DEMANDÉS par l'utilisateur (on part de / on va
    # à son mouillage), JAMAIS à une arrivée DÉPLACÉE par le moteur : une
    # arrivée relogée à 200 m d'une bouée levait l'écart minimal → la route
    # passait dessus.
    exempt = (a, orig_end)

    # ── Passe 1 : GROSSIÈRE (toute la zone, max-pooling) ────────────────
    try:
        try:
            coarse = _solve_leg(
                grid, a, b, min_depth, lateral_margin_m,
                max_px=MAX_DIM, pad_min=PAD_MIN_DEG, do_round=False, strict_depth=strict_depth,
                strict_exempt=exempt, trap_check=True, trap_end=(end_snap is None),
            )
        except _LegBlocked as lb:
            # 22/07/2026 (bug armateur « je ne peux faire aucune route ») —
            # le DÉTOUR nécessaire peut sortir de la fenêtre de recherche
            # (ex. Arradon → Pénerf : la sortie du Golfe par Port-Navalo est
            # HORS de la bbox départ→arrivée). On réessaie avec des fenêtres
            # progressivement élargies avant de conclure au blocage réel.
            coarse = None
            for pf, pm in ((1.2, 0.15), (2.5, 0.40)):
                try:
                    coarse = _solve_leg(
                        grid, a, b, min_depth, lateral_margin_m,
                        max_px=MAX_DIM, pad_min=pm, do_round=False,
                        strict_depth=strict_depth, strict_exempt=exempt,
                        trap_check=True, trap_end=(end_snap is None), pad_frac=pf,
                    )
                    break
                except _LegBlocked as lb2:
                    lb = lb2
                except _SnapFail:
                    # maille plus grossière → snap perdu : le diagnostic de
                    # la 1re fenêtre (lb) reste le plus fiable.
                    break
            if coarse is None:
                # Dernier recours (22/07) : si la composante du départ frôle
                # déjà la destination (≤ END_SNAP_MAX_M — rivière d'Auray dont les
                # derniers kilomètres sont fermés par le balisage à maille
                # grossière), on livre la route jusqu'au point atteignable
                # le plus proche, annoncé comme « arrivée déplacée ».
                blk = lb.blocked_at
                ref = end_snap["requested"] if end_snap else {"lat": end_lat, "lng": end_lng}
                d_blk = math.hypot(
                    (blk[0] - ref["lat"]) * M_PER_DEG_LAT,
                    (blk[1] - ref["lng"]) * m_per_deg_lng(ref["lat"]),
                )
                if d_blk <= _trunc_cap_m(a, ref) and len(lb.partial_pts) >= 2:
                    end_lat, end_lng = blk
                    b = (end_lat, end_lng)
                    end_snap = {
                        "requested": {"lat": ref["lat"], "lng": ref["lng"]},
                        "offset_m": round(d_blk),
                    }
                    # Le chemin PARTIEL de l'A* va exactement au point
                    # atteignable le plus proche : on le prend comme passe
                    # grossière (step 2 → raffinement fin systématique).
                    coarse = {"raw": lb.partial_pts, "step": 2}
            if coarse is None:
                raise RouteError("no_route", MSG_BLOCKED, payload=_blocked_payload(lb.blocked_at, lb.partial_pts))
    except _SnapFail as sf:
        if sf.which == "start":
            raise RouteError(
                "start_blocked",
                "Départ dans une zone non navigable pour ce tirant d'eau (ou trop près du bord).",
                payload={"blocked_at": {"lat": round(start_lat, 6), "lng": round(start_lng, 6)}},
            )
        raise RouteError(
            "end_blocked",
            "Destination non navigable pour ce tirant d'eau (ou trop près du bord).",
            payload={"blocked_at": {"lat": round(end_lat, 6), "lng": round(end_lng, 6)}},
        )

    # ── Passe 2 : RAFFINEMENT par tronçon (fenêtres fines) ──────────────
    moorings_local_crossed = False
    if coarse["step"] > 1:
        src = coarse["raw"]          # tracé lissé (peu de points, longs segments)
        pts: list[tuple[float, float]] = [src[0]]
        cur = src[0]
        n = len(src)
        for k in range(1, n):
            target = src[k]
            is_last = k == n - 1
            if not is_last:
                # 22/07 (fix asymétrie 50 m) — MICRO-tronçon (< 150 m) :
                # fenêtre dégénérée → faux blocage. Fusionné avec le suivant.
                d_m = math.hypot(
                    (target[0] - cur[0]) * M_PER_DEG_LAT,
                    (target[1] - cur[1]) * m_per_deg_lng(cur[0]),
                )
                if d_m < 150.0:
                    continue
            try:
                try:
                    leg = _solve_leg(
                        grid, cur, target, min_depth, lateral_margin_m,
                        max_px=FINE_DIM, pad_min=FINE_PAD_MIN_DEG, do_round=False,
                        strict_depth=strict_depth,
                    )
                except _LegBlocked:
                    # 2e chance : fenêtre ÉLARGIE (le détour peut sortir de la
                    # petite fenêtre du tronçon — asymétrie aller/retour).
                    leg = _solve_leg(
                        grid, cur, target, min_depth, lateral_margin_m,
                        max_px=MAX_DIM, pad_min=PAD_MIN_DEG, do_round=False,
                        strict_depth=strict_depth,
                    )
            except (_SnapFail, _LegBlocked) as err:
                # 27/07 (iter118, Vilaine tronquée à 3,9 km du barrage) — le
                # tronçon peut être fermé par des ZONES DE MOUILLAGE (trots
                # le long des rivières) : on le retente en les ouvrant
                # LOCALEMENT (jamais les parcs de culture marine), avec
                # avertissement, avant de sauter/tronquer.
                if not MOORINGS_OPEN.get():
                    tok_lm = MOORINGS_OPEN.set(True)
                    try:
                        leg = _solve_leg(
                            grid, cur, target, min_depth, lateral_margin_m,
                            max_px=FINE_DIM, pad_min=FINE_PAD_MIN_DEG,
                            do_round=False, strict_depth=strict_depth,
                        )
                    except (_SnapFail, _LegBlocked):
                        leg = None
                    finally:
                        MOORINGS_OPEN.reset(tok_lm)
                    if leg is not None:
                        moorings_local_crossed = True
                        pts.extend(leg["raw"][1:])
                        cur = leg["raw"][-1]
                        continue
                if not is_last:
                    # Cible INTERMÉDIAIRE infranchissable en fin (waypoint
                    # grossier tombé dans une zone interdite pleine
                    # résolution) : on la SAUTE — le tronçon suivant reliera
                    # directement cur au waypoint d'après.
                    continue
                # 22/07/2026 (bug armateur « je ne peux faire aucune route »)
                # — cur lui-même peut être un waypoint grossier tombé dans
                # une POCHE d'exclusion en pleine résolution (cluster de
                # balises de Conleau, chenal de Vannes) : on RECULE de
                # quelques waypoints et on retente directement vers la cible
                # avec la grande fenêtre.
                leg = None
                for back in (2, 3, 5):
                    if len(pts) < back:
                        break
                    try:
                        leg = _solve_leg(
                            grid, pts[-back], target, min_depth, lateral_margin_m,
                            max_px=MAX_DIM, pad_min=PAD_MIN_DEG, do_round=False,
                            strict_depth=strict_depth,
                        )
                    except (_SnapFail, _LegBlocked):
                        continue
                    del pts[-(back - 1):]
                    break
                if leg is None:
                    # Même filet qu'en passe 1 (22/07) : si le blocage est
                    # déjà « presque arrivé » (< 2,5 km — haute rivière
                    # d'Auray discontinue dans le MNT), on livre la route
                    # jusqu'au point atteignable, annoncé « arrivée déplacée ».
                    blk = err.blocked_at if isinstance(err, _LegBlocked) else cur
                    ref = end_snap["requested"] if end_snap else {"lat": end_lat, "lng": end_lng}
                    d_blk = math.hypot(
                        (blk[0] - ref["lat"]) * M_PER_DEG_LAT,
                        (blk[1] - ref["lng"]) * m_per_deg_lng(ref["lat"]),
                    )
                    if d_blk <= _trunc_cap_m(a, ref):
                        cand = pts + (
                            err.partial_pts[1:]
                            if isinstance(err, _LegBlocked) and len(err.partial_pts) >= 2
                            else []
                        )
                        # 23/07/2026 (bug Brest→La Rochelle) — l'extrémité
                        # RÉELLE du tracé doit être proche du point demandé,
                        # pas seulement le point de blocage : sinon on livrait
                        # une route tronquée annoncée « arrivée déplacée ».
                        d_end = math.hypot(
                            (cand[-1][0] - ref["lat"]) * M_PER_DEG_LAT,
                            (cand[-1][1] - ref["lng"]) * m_per_deg_lng(ref["lat"]),
                        )
                        if d_end <= _trunc_cap_m(a, ref):
                            pts = cand
                            end_lat, end_lng = pts[-1]
                            b = (end_lat, end_lng)
                            end_snap = {
                                "requested": {"lat": ref["lat"], "lng": ref["lng"]},
                                "offset_m": round(d_end),
                            }
                            break
                    if isinstance(err, _LegBlocked):
                        partial = pts + err.partial_pts[1:]
                        raise RouteError("no_route", MSG_BLOCKED, payload=_blocked_payload(err.blocked_at, partial))
                    raise RouteError("no_route", MSG_BLOCKED, payload=_blocked_payload(cur, pts))
            pts.extend(leg["raw"][1:])
            cur = leg["raw"][-1]
    else:
        pts = list(coarse["raw"])

    # ── Passe 3 : REDRESSEMENT + ARRONDI globaux (22/07, lot armateur) ──
    # Couloir contrôlé en PLEINE résolution + écart minimal aux balises et
    # dangers (roches/épaves/obstructions) : supprime les crochets
    # injustifiés hérités des fenêtres grossière/fines.
    seamarks = get_seamarks()
    clearance: Optional[np.ndarray] = None
    gates_arr: Optional[np.ndarray] = None
    if seamarks is not None:
        la = [p[0] for p in pts]
        lo = [p[1] for p in pts]
        cl = seamarks.clearance_points(
            min(la) - 0.01, max(la) + 0.01, min(lo) - 0.01, max(lo) + 0.01, min_depth,
        )
        if cl:
            clearance = np.asarray(cl, dtype=np.float64)
        # 28/07 (contrainte dure de chenal) — PORTES pour les contrôles
        # pleine résolution (_corridor_safe) : mêmes murs que le masque A*,
        # exemption 400 m autour du départ/de l'arrivée DEMANDÉS.
        mlng_g = m_per_deg_lng((min(la) + max(la)) / 2)
        ga = [
            g for g in seamarks.gates(
                min(la) - 0.01, max(la) + 0.01, min(lo) - 0.01, max(lo) + 0.01)
            if not any(
                math.hypot((g[0] - p[0]) * M_PER_DEG_LAT,
                           (g[1] - p[1]) * mlng_g) < MOORING_EXEMPT_M
                for p in exempt
            )
        ]
        if ga:
            gates_arr = np.asarray(ga, dtype=np.float64)
    # Extrémités AVANT la passe 3 (23/07) : point EXACT de l'utilisateur si
    # navigable en profondeur, sinon accrochage PLEINE résolution (jamais sur
    # un estran). Placées ICI pour que la RÉPARATION sécurise aussi les
    # premiers/derniers segments (avant, la restauration après-coup pouvait
    # réintroduire un caillou évité par l'A* à 40 m du départ).
    d_start = grid.depth_at(start_lat, start_lng)
    d_end = grid.depth_at(end_lat, end_lng)
    if d_start is not None and d_start >= min_depth:
        pts[0] = (start_lat, start_lng)
    else:
        s2 = _snap_fullres(grid, start_lat, start_lng, min_depth)
        if s2 is not None:
            pts[0] = s2
    if d_end is not None and d_end >= min_depth:
        pts[-1] = (end_lat, end_lng)
    else:
        e2 = _snap_fullres(grid, end_lat, end_lng, min_depth)
        if e2 is not None:
            pts[-1] = e2

    pts = _repair_segments(grid, pts, min_depth, lateral_margin_m, clearance,
                           strict_depth, strict_exempt=exempt, gates_arr=gates_arr)
    pts = _straighten(grid, pts, min_depth, lateral_margin_m, clearance,
                      gates_arr=gates_arr, strict_depth_w=strict_depth)
    pts = _round_pts(grid, pts, min_depth, lateral_margin_m, clearance,
                     gates_arr=gates_arr, strict_depth_w=strict_depth)

    waypoints = [{"lat": round(p[0], 6), "lng": round(p[1], 6)} for p in pts]
    result = _result_for(grid, waypoints, min_depth)
    # 23/07 (extension de zone) — REFUS FERME au-delà de la tolérance (0.45 m
    # = quantification des données + marge partiellement consommée) : sur
    # données 100 m, un simple « warning » à -1 m serait une route à
    # l'échouage. Dans la bande [seuil-0.45, seuil[, la route passe AVEC
    # avertissement explicite (profil affiché). Le pire point est montré sur
    # la carte comme un blocage classique.
    if result["min_depth_m"] is not None and result["min_depth_m"] < min_depth - 0.45:
        # 22/07/2026 — arrivée déjà DÉPLACÉE (end_snap) : le point trop haut
        # est souvent la toute FIN du tracé (cellule grossière optimiste sur
        # l'estran/la rivière). On RECULE l'arrivée waypoint par waypoint
        # (≤ 1,5 km) jusqu'à un profil sain avant de refuser.
        trimmed = False
        if end_snap is not None and len(waypoints) > 2:
            ref = end_snap["requested"]
            budget = 1500.0
            wps = list(waypoints)
            while len(wps) > 2 and budget > 0:
                seg = math.hypot(
                    (wps[-1]["lat"] - wps[-2]["lat"]) * M_PER_DEG_LAT,
                    (wps[-1]["lng"] - wps[-2]["lng"]) * m_per_deg_lng(wps[-1]["lat"]),
                )
                # 23/07/2026 (bug Brest→La Rochelle) — waypoints ESPACÉS des
                # routes longues (60+ km) : un seul pop amputait 300 km d'un
                # coup (le budget n'était vérifié qu'APRÈS). On n'ampute
                # jamais plus que le budget restant.
                if seg > budget:
                    break
                wps.pop()
                budget -= seg
                r2 = _result_for(grid, wps, min_depth)
                if r2["min_depth_m"] is None or r2["min_depth_m"] >= min_depth - 0.45:
                    waypoints, result = wps, r2
                    end_lat, end_lng = wps[-1]["lat"], wps[-1]["lng"]
                    end_snap["offset_m"] = round(math.hypot(
                        (end_lat - ref["lat"]) * M_PER_DEG_LAT,
                        (end_lng - ref["lng"]) * m_per_deg_lng(ref["lat"]),
                    ))
                    trimmed = True
                    break
        if not trimmed and not _strict_retry:
            # 26/07 (bug Vilaine à marée haute) — l'A*/réparation décimé peut
            # couper sur une vasière limite que le contrôle final pleine
            # résolution refuse (< seuil-0,45). UN SEUL re-calcul avec marge
            # de fond renforcée (+0,5 m) : le masque referme les bancs
            # limites et la route retombe dans le vrai chenal.
            try:
                return compute_route(
                    start_lat, start_lng, orig_end[0], orig_end[1],
                    draft_m, depth_margin_m + 0.5, lateral_margin_m,
                    tide_m, _strict_retry=True,
                )
            except RouteError:
                pass
        if not trimmed:
            prof = [p for p in result.get("depth_profile", []) if p.get("depth_m") is not None]
            worst = min(prof, key=lambda p: p["depth_m"]) if prof else None
            payload = {"blocked_at": {"lat": worst["lat"], "lng": worst["lng"]}} if worst else None
            raise RouteError("no_route", MSG_BLOCKED, payload)
    result["mode"] = "auto"
    result["tide_m"] = round(tide_m, 2)
    # 22/07 — corridor de navigation DYNAMIQUE par segment (alerte d'écart).
    result["corridor_m"] = _corridors_for(grid, waypoints, min_depth, lateral_margin_m, clearance)
    # 22/07 — passage possible UNIQUEMENT grâce à la marée : alerte explicite.
    base_threshold = draft_m + depth_margin_m
    if tide_m > 0.05 and result["min_depth_m"] is not None and result["min_depth_m"] < base_threshold:
        result["warnings"].insert(0, (
            f"Passage possible UNIQUEMENT grâce à la marée (+{tide_m:.1f} m au moment "
            f"du calcul) : fond mini {result['min_depth_m']:.1f} m sur la carte pour un "
            f"besoin de {base_threshold:.1f} m à marée basse. Re-vérifiez la hauteur "
            "d'eau à votre heure de passage (actualisez la route à l'approche)."
        ))
    if end_snap is not None:
        result["end_snapped"] = end_snap
        if end_snap["offset_m"] >= 300:
            result["warnings"].insert(0, (
                f"Destination non navigable à cette hauteur d'eau (estran / zone "
                f"découvrante) — arrivée déplacée vers l'eau navigable la plus "
                f"proche, à ~{end_snap['offset_m']} m du point demandé."
            ))
    # 27/07 — audit final : passage trop près d'une balise → avertissement
    # nominatif (jamais silencieux).
    result["warnings"].extend(_mark_pass_audit(waypoints, (a, orig_end)))
    if moorings_local_crossed:
        result["warnings"].insert(0, (
            "⚠ Zones de mouillage traversées localement (aucun passage "
            "libre) — vitesse très réduite, attention aux corps-morts et "
            "aux bateaux au mouillage."
        ))
        result["through_moorings"] = True
    # Parcs de culture marine : le masque fin les interdit ; si malgré tout
    # (géométrie sans issue) le tracé en coupe un, on le dit HAUT ET FORT.
    if _crosses_farm(waypoints):
        result["warnings"].insert(0, (
            "⚠ DANGER : le tracé coupe un PARC DE CULTURE MARINE (aucun "
            "passage libre trouvé) — ne suivez pas ce tronçon, contournez "
            "la zone à vue."
        ))
    return result


def shallow_legs(waypoints: list[dict], min_depth: float) -> list[int]:
    """29/07/2026 (façon Navionics) — indices des tronçons dont la ligne
    centrale traverse une cellule terre/sans donnée OU un fond carte
    < min_depth (pas PROFILE_STEP_M). Partagé par la route manuelle
    (tronçons rouges) et le mode « eau peu profonde » de la route auto."""
    grid = get_grid()
    if grid is None or len(waypoints) < 2:
        return []
    lat_mid = sum(w["lat"] for w in waypoints) / len(waypoints)
    out: list[int] = []
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        seg_m = math.hypot(
            (b["lat"] - a["lat"]) * M_PER_DEG_LAT,
            (b["lng"] - a["lng"]) * m_per_deg_lng(lat_mid),
        )
        n = max(2, int(seg_m / PROFILE_STEP_M) + 1)
        for k in range(n + 1):
            t = k / n
            lat = a["lat"] + (b["lat"] - a["lat"]) * t
            lng = a["lng"] + (b["lng"] - a["lng"]) * t
            if not grid.covers(lat, lng):
                continue  # hors couverture = inconnu, pas « compromis »
            d = grid.depth_at(lat, lng)
            if d is None or float(d) < min_depth:
                out.append(i)
                break
    return out


def manual_route(
    waypoints_in: list[tuple[float, float]], draft_m: float, depth_margin_m: float,
    tide_m: float = 0.0,
) -> dict:
    """Route MANUELLE (22/07/2026) : les waypoints de l'utilisateur sont pris
    TELS QUELS (aucun A*), on calcule distance + profil de profondeur +
    avertissements. Fonctionne aussi hors couverture bathy (profil vide).

    27/07 (vidéo armateur 15h45, « zones rouges alors qu'il y a 5 m d'eau ») :
    tide_m intègre la MARÉE comme la route auto — les tronçons ne sont plus
    marqués rouges au ZH quand la hauteur d'eau réelle suffit. Et le tracé
    est audité contre les zones interdites (parcs de culture marine, zones
    de mouillage) + l'écart minimal aux balises."""
    grid = get_grid()
    draft_m = float(np.clip(draft_m, DRAFT_MIN, DRAFT_MAX))
    depth_margin_m = float(np.clip(depth_margin_m, DEPTH_MARGIN_MIN, DEPTH_MARGIN_MAX))
    tide_m = float(np.clip(tide_m, -2.0, 6.0))
    min_depth = max(draft_m + depth_margin_m - tide_m, -2.5)
    waypoints = [{"lat": round(lat, 6), "lng": round(lng, 6)} for lat, lng in waypoints_in]
    result = _result_for(grid, waypoints, min_depth)
    result["mode"] = "manual"
    # 24/07/2026 (demande armateur) — TRONÇONS COMPROMIS : chaque segment de
    # la route manuelle est échantillonné ; s'il traverse une cellule terre /
    # sans donnée OU un fond insuffisant, son index est renvoyé → le front
    # l'affiche EN ROUGE et exige l'acceptation du risque avant le suivi.
    # 29/07 — factorisé dans shallow_legs (partagé avec la route auto).
    compromised: list[int] = shallow_legs(waypoints, min_depth)
    if compromised:
        result["compromised_legs"] = compromised
        result["risk"] = True  # suivi conditionné à l'acceptation du risque
        result["warnings"].insert(
            0,
            f"{len(compromised)} tronçon(s) EN ROUGE : fond insuffisant ou "
            "terre sur le trajet — acceptation du risque exigée avant de "
            "suivre cette route.",
        )
    result["tide_m"] = round(tide_m, 2)
    # ── 27/07 (vidéo 15h45, mouillages de Barrarach + parcs) — le tracé
    # manuel est AUDITÉ contre les zones interdites : parcs de culture
    # marine (aucune exemption) et zones/bouées de mouillage (exemptées à
    # < 400 m du premier/dernier waypoint : on part de / on va à son
    # mouillage). Tronçons fautifs EN ROUGE + avertissement explicite.
    seamarks = get_seamarks()
    if seamarks is not None and grid is not None and len(waypoints) >= 2:
        lat_mid = sum(w["lat"] for w in waypoints) / len(waypoints)
        mlng = m_per_deg_lng(lat_mid)
        la = [w["lat"] for w in waypoints]
        lo = [w["lng"] for w in waypoints]
        ends = (waypoints[0], waypoints[-1])

        def _in_bbox(arr: np.ndarray) -> np.ndarray:
            return arr[(arr[:, 0] >= min(la) - 0.01) & (arr[:, 0] <= max(la) + 0.01)
                       & (arr[:, 1] >= min(lo) - 0.01) & (arr[:, 1] <= max(lo) + 0.01)]

        def _not_near_ends(arr: np.ndarray) -> np.ndarray:
            keep = np.ones(len(arr), dtype=bool)
            for e in ends:
                dd = np.hypot((arr[:, 0] - e["lat"]) * M_PER_DEG_LAT,
                              (arr[:, 1] - e["lng"]) * mlng)
                keep &= dd >= MOORING_EXEMPT_M
            return arr[keep]

        groups: list[tuple[np.ndarray, str]] = []
        if len(seamarks.farm_circles):
            g = _in_bbox(seamarks.farm_circles)
            if len(g):
                groups.append((g, "un parc de culture marine (passage interdit)"))
        anch = _in_bbox(seamarks.anchorage_circles) if len(seamarks.anchorage_circles) else np.zeros((0, 3))
        moor = np.asarray(
            [(mo["lat"], mo["lng"], R_MOORING_M) for mo in seamarks.moorings],
            dtype=np.float64,
        ) if seamarks.moorings else np.zeros((0, 3))
        moor_all = np.vstack([anch, _in_bbox(moor) if len(moor) else moor])
        if len(moor_all):
            g = _not_near_ends(moor_all)
            if len(g):
                groups.append((g, "une zone de mouillage (corps-morts, bouées)"))

        zone_legs: list[int] = []
        zone_msgs: list[str] = []
        for circles, label in groups:
            hit_legs: set[int] = set()
            for i in range(len(waypoints) - 1):
                a, b = waypoints[i], waypoints[i + 1]
                seg_m = math.hypot((b["lat"] - a["lat"]) * M_PER_DEG_LAT,
                                   (b["lng"] - a["lng"]) * mlng)
                n = max(2, int(seg_m / 20.0) + 1)
                tt = np.linspace(0.0, 1.0, n + 1)
                s_lat = a["lat"] + (b["lat"] - a["lat"]) * tt
                s_lng = a["lng"] + (b["lng"] - a["lng"]) * tt
                dy = (s_lat[:, None] - circles[None, :, 0]) * M_PER_DEG_LAT
                dx = (s_lng[:, None] - circles[None, :, 1]) * mlng
                if bool((dy * dy + dx * dx <= circles[None, :, 2] ** 2).any()):
                    hit_legs.add(i)
            if hit_legs:
                zone_legs.extend(hit_legs)
                zone_msgs.append(
                    f"⚠ Le tracé traverse {label} — tronçon(s) en rouge : "
                    "modifiez la route pour contourner la zone."
                )
        if zone_legs:
            merged = sorted(set(result.get("compromised_legs", [])) | set(zone_legs))
            result["compromised_legs"] = merged
            result["risk"] = True
            for msg in zone_msgs:
                result["warnings"].insert(0, msg)
        # Écart minimal aux balises (audit nominatif, mêmes règles que l'auto).
        result["warnings"].extend(_mark_pass_audit(
            waypoints, ((ends[0]["lat"], ends[0]["lng"]), (ends[1]["lat"], ends[1]["lng"])),
        ))
    # 22/07 — corridor dynamique aussi pour les routes manuelles/enregistrées.
    seamarks = get_seamarks()
    clearance = None
    if seamarks is not None and waypoints:
        la = [w["lat"] for w in waypoints]
        lo = [w["lng"] for w in waypoints]
        cl = seamarks.clearance_points(
            min(la) - 0.01, max(la) + 0.01, min(lo) - 0.01, max(lo) + 0.01, min_depth,
        )
        if cl:
            clearance = np.asarray(cl, dtype=np.float64)
    result["corridor_m"] = _corridors_for(grid, waypoints, min_depth, 10.0, clearance)
    return result
