"""SignalMar — Post-correction « ÉCART MINIMAL AUX BALISES » (02/08/2026).

Variante **Moteur B** (algo ``signalmar.v2``). Corrige le défaut constaté par
l'armateur le 02/08 (capture 08:47, balise verte « Fernais 25 », estuaire de
la Loire) : en marge AUTO, la route passait à **4,7 m** de la balise.

CAUSE RACINE (mesurée, cf. scripts/diag_fernais.py) :
  1. l'écart minimal autour des balises (``R_MARK_STANDOFF_M`` = 60 m,
     rasterisé dans le masque A*) est **SAUTÉ dès que la maille dépasse
     45 m** (garde-fou du 28/07 : en maille grossière un disque de 60 m
     scellerait des chenaux entiers) ;
  2. hors zone pilote (Golfe du Morbihan, MNT 20 m) la seule bathymétrie
     disponible est l'ATL100 → maille réelle 75-110 m dans les fenêtres de
     raffinement → **l'écart minimal n'est JAMAIS appliqué** sur toute la
     façade, Loire comprise ;
  3. en marge AUTO (plancher 10 m) l'érosion du masque est nulle (10 m ≪
     maille), alors qu'en marge MANUELLE 50 m elle vaut 1 cellule (~75 m) —
     d'où la différence observée par l'armateur entre les deux modes.

CORRECTIF (indépendant de la maille) : après le calcul complet du moteur
historique, on vérifie GÉOMÉTRIQUEMENT le tracé final (pleine résolution) et
on l'écarte des balises quand il y a la place — chaque déviation candidate
est re-validée exactement comme le fait le moteur (fond ≥ seuil sur un
couloir, écart aux autres balises/dangers, murs de porte de chenal). S'il n'y
a PAS la place, le tracé historique est conservé tel quel avec son
avertissement nominatif : aucune route n'est jamais perdue.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np

from core.bathy import M_PER_DEG_LAT, get_grid, m_per_deg_lng
from core.routing_engines.algos.signalmar_v1 import core as v1
from core.seamarks import MOORING_EXEMPT_M, get_seamarks

#: Paramètres surchargeables depuis le document Moteur (champ ``params``).
DEFAULT_PARAMS: dict[str, Any] = {
    # Interrupteur général de la post-correction.
    "standoff_enforce": True,
    # Garde ajoutée à l'écart recommandé de la balise (le tracé visé passe
    # donc à ``r_std + pad``, ex. 60 + 10 = 70 m de « Fernais 25 »).
    "standoff_pad_m": 10.0,
    # Rallonge maximale acceptée pour un contournement (par balise).
    "standoff_max_detour_m": 600.0,
    # Abords du départ / de l'arrivée DEMANDÉS : on ne déplace rien (on part
    # de son mouillage, on rejoint son ponton).
    "standoff_exempt_m": 200.0,
    # Nombre de balises corrigées au maximum (sécurité perf).
    "standoff_max_marks": 12,
}


def merge_params(params: Optional[dict]) -> dict[str, Any]:
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update({k: v for k, v in params.items() if k in DEFAULT_PARAMS})
    return p


# ── Géométrie locale (mètres) ─────────────────────────────────────────────
def _d_m(p: tuple[float, float], m_lat: float, m_lng: float, mlng: float) -> float:
    return math.hypot((p[0] - m_lat) * M_PER_DEG_LAT, (p[1] - m_lng) * mlng)


def _closest_on(
    pts: list[tuple[float, float]], m_lat: float, m_lng: float, mlng: float,
) -> tuple[float, int, tuple[float, float]]:
    """(distance_m, index du segment, point le plus proche) du tracé à la balise."""
    best = (float("inf"), 0, pts[0])
    for i in range(len(pts) - 1):
        ax = (pts[i][1] - m_lng) * mlng
        ay = (pts[i][0] - m_lat) * M_PER_DEG_LAT
        bx = (pts[i + 1][1] - m_lng) * mlng
        by = (pts[i + 1][0] - m_lat) * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 <= 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / L2))
        d = math.hypot(ax + t * dx, ay + t * dy)
        if d < best[0]:
            p = (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t,
                 pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t)
            best = (d, i, p)
    return best


def _length_m(pts: list[tuple[float, float]], mlng: float) -> float:
    return sum(
        math.hypot((pts[i + 1][0] - pts[i][0]) * M_PER_DEG_LAT,
                   (pts[i + 1][1] - pts[i][1]) * mlng)
        for i in range(len(pts) - 1)
    )


class _Ctx:
    """Contexte de validation — mêmes contrôles que la passe 3 du moteur."""

    def __init__(self, grid, min_depth: float, lateral_margin_m: float,
                 clearance, gates_arr, strict_depth: float, mlng: float) -> None:
        self.grid = grid
        self.min_depth = min_depth
        self.lateral = lateral_margin_m
        self.clearance = clearance
        self.gates = gates_arr
        self.strict = strict_depth
        self.mlng = mlng

    def seg_ok(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        """Fond ≥ seuil sur le couloir + murs de porte de chenal. L'écart aux
        balises/dangers n'est PAS vérifié ici : il l'est en NON-RÉGRESSION
        (``_clearance_not_worse``) — le tracé d'origine viole déjà certains
        cercles (c'est le bug qu'on corrige), un contrôle absolu rejetterait
        toutes les déviations dans un chenal balisé."""
        return v1._corridor_safe(
            self.grid, a, b, self.min_depth, self.lateral, None,
            half_m=15.0, gates_arr=self.gates, strict_depth_w=self.strict,
        )

    def point_ok(self, p: tuple[float, float]) -> bool:
        d = self.grid.depth_at(p[0], p[1])
        return d is not None and float(d) >= self.min_depth


def _near_circles(clearance, m_lat: float, m_lng: float, mlng: float,
                  radius_m: float = 1500.0):
    """Cercles d'écart (balises/dangers/parcs) au voisinage de la balise."""
    if clearance is None or not len(clearance):
        return None
    d = np.hypot((clearance[:, 0] - m_lat) * M_PER_DEG_LAT,
                 (clearance[:, 1] - m_lng) * mlng)
    sel = clearance[d <= radius_m]
    return sel if len(sel) else None


def _min_dists(pts: list[tuple[float, float]], circles, mlng: float):
    """Distance minimale du tracé à CHAQUE cercle (vectorisé)."""
    P = np.asarray(pts, dtype=np.float64)
    ax = (P[:-1, 1][None, :] - circles[:, 1][:, None]) * mlng
    ay = (P[:-1, 0][None, :] - circles[:, 0][:, None]) * M_PER_DEG_LAT
    bx = (P[1:, 1][None, :] - circles[:, 1][:, None]) * mlng
    by = (P[1:, 0][None, :] - circles[:, 0][:, None]) * M_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.clip(-(ax * dx + ay * dy) / np.where(L2 > 0, L2, 1.0), 0.0, 1.0)
    return np.hypot(ax + t * dx, ay + t * dy).min(axis=1)


def _score(pts: list[tuple[float, float]], circles, mlng: float) -> tuple[float, float]:
    """Qualité d'écartement locale : (pire ratio écart/consigne, moyenne).
    1.0 = toutes les consignes d'écart respectées."""
    if circles is None:
        return (1.0, 1.0)
    d = _min_dists(pts, circles, mlng)
    ratio = np.minimum(d / np.maximum(circles[:, 2], 1.0), 1.0)
    return (float(ratio.min()), float(ratio.mean()))


def _best_insert_index(base: list[tuple[float, float]], q: tuple[float, float],
                       mlng: float, around: int) -> int:
    """Segment où insérer ``q`` en rallongeant le moins (recherche locale)."""
    best, best_j = float("inf"), around
    for j in range(max(0, around - 2), min(len(base) - 1, around + 3)):
        a, b = base[j], base[j + 1]
        add = (math.hypot((q[0] - a[0]) * M_PER_DEG_LAT, (q[1] - a[1]) * mlng)
               + math.hypot((b[0] - q[0]) * M_PER_DEG_LAT, (b[1] - q[1]) * mlng)
               - math.hypot((b[0] - a[0]) * M_PER_DEG_LAT, (b[1] - a[1]) * mlng))
        if add < best:
            best, best_j = add, j
    return best_j


def _fix_one_mark(
    pts: list[tuple[float, float]], m_lat: float, m_lng: float, target: float,
    ctx: _Ctx, max_detour_m: float,
) -> Optional[list[tuple[float, float]]]:
    """Écarte le tracé de la balise (cible ``target`` m) en MAXIMISANT l'écart
    aux balises voisines — cas typique : une paire de bouées de chenal, où il
    faut viser le milieu du couloir plutôt que fuir une seule bouée. Retourne
    le nouveau tracé, ou None s'il n'y a pas la place (tracé conservé)."""
    mlng = ctx.mlng
    n0 = len(pts)
    # 1. Les waypoints INTÉRIEURS tombés dans le disque sont retirés (le
    #    contournement les remplacera) — extrémités jamais touchées.
    base = [p for k, p in enumerate(pts)
            if k in (0, n0 - 1) or _d_m(p, m_lat, m_lng, mlng) >= target]
    if len(base) < 2:
        return None
    len0 = _length_m(pts, mlng)
    circles = _near_circles(ctx.clearance, m_lat, m_lng, mlng)
    score0 = _score(pts, circles, mlng)

    d, i, P = _closest_on(base, m_lat, m_lng, mlng)
    # Direction d'écartement = côté où la route passe DÉJÀ (on ne change
    # jamais de côté d'une balise : le côté est imposé par le balisage).
    ex = (P[1] - m_lng) * mlng
    ey = (P[0] - m_lat) * M_PER_DEG_LAT
    norm = math.hypot(ex, ey)
    if norm < 1.0:
        # Tracé pile sur la balise : on prend la perpendiculaire au segment.
        a, b = base[i], base[i + 1]
        sx = (b[1] - a[1]) * mlng
        sy = (b[0] - a[0]) * M_PER_DEG_LAT
        sn = math.hypot(sx, sy) or 1.0
        ex, ey, norm = -sy / sn, sx / sn, 1.0
    ux, uy = ex / norm, ey / norm

    def _pt(vx: float, vy: float, r: float) -> tuple[float, float]:
        return (m_lat + (vy * r) / M_PER_DEG_LAT, m_lng + (vx * r) / mlng)

    cands: list[tuple[float, float]] = []
    for extra in (0.0, 15.0, 40.0, 80.0):
        for ang_deg in (0.0, 20.0, -20.0, 40.0, -40.0):
            ca, sa = math.cos(math.radians(ang_deg)), math.sin(math.radians(ang_deg))
            cands.append(_pt(ux * ca - uy * sa, ux * sa + uy * ca, target + extra))
    # Milieu de couloir : entre la balise et chaque danger voisin (paire de
    # bouées, roche…) — c'est là que l'écart est maximal des deux côtés.
    if circles is not None:
        for row in circles:
            gap = _d_m((row[0], row[1]), m_lat, m_lng, mlng)
            if gap < 25.0 or gap > 900.0:
                continue
            wx = ((row[1] - m_lng) * mlng) / gap
            wy = ((row[0] - m_lat) * M_PER_DEG_LAT) / gap
            for frac in (0.5, 0.4, 0.6):
                cands.append(_pt(wx, wy, gap * frac))

    scored: list[tuple[tuple[float, float], float, list, int]] = []
    for q in cands:
        j = _best_insert_index(base, q, mlng, i)
        cand = base[:j + 1] + [q] + base[j + 1:]
        det = _length_m(cand, mlng) - len0
        if det > max_detour_m:
            continue
        d2, _, _ = _closest_on(cand, m_lat, m_lng, mlng)
        if d2 < min(target, d + 8.0) - 2.0:
            continue
        sc = _score(cand, circles, mlng)
        if sc <= score0:
            continue
        scored.append((sc, det, cand, j))
    if not scored:
        return None
    # Meilleur écartement d'abord ; à qualité égale, le détour le plus court.
    scored.sort(key=lambda t: (-t[0][0], -t[0][1], t[1]))

    for (_sc, _det, cand, j) in scored[:8]:
        q = cand[j + 1]
        if not ctx.point_ok(q):
            continue
        lo = max(0, j - 1)
        hi = min(len(cand) - 1, j + 3)
        if all(ctx.seg_ok(cand[k], cand[k + 1]) for k in range(lo, hi)):
            return cand
    return None


def rebuild_result(
    result: dict, grid, pts: list[tuple[float, float]], *,
    min_depth: float, lateral_margin_m: float,
    exempt: tuple[tuple[float, float], tuple[float, float]],
    clearance=None, extra_warnings: tuple[str, ...] = (),
) -> dict:
    """Recalcule tous les champs dépendants de la GÉOMÉTRIE après modification
    du tracé (distance, fond mini, profil, couloirs, avertissements)."""
    new_wps = [{"lat": round(q[0], 6), "lng": round(q[1], 6)} for q in pts]
    fresh = v1._result_for(grid, new_wps, min_depth)
    out = dict(result)
    out["waypoints"] = fresh["waypoints"]
    out["distance_m"] = fresh["distance_m"]
    out["min_depth_m"] = fresh["min_depth_m"]
    out["depth_profile"] = fresh["depth_profile"]
    out["corridor_m"] = v1._corridors_for(
        grid, new_wps, min_depth, lateral_margin_m, clearance)
    # Avertissements : on purge ceux qui dépendent du tracé puis on ré-audite.
    kept = [
        w for w in (result.get("warnings") or [])
        if not w.startswith("⚠ La route passe à ~") and not w.startswith("Passage à ")
    ]
    kept.extend(fresh.get("warnings") or [])
    kept.extend(v1._mark_pass_audit(new_wps, exempt))
    kept.extend(extra_warnings)
    out["warnings"] = list(dict.fromkeys(kept))
    return out


def enforce_mark_standoff(
    result: dict, *,
    start: tuple[float, float], requested_end: tuple[float, float],
    min_depth: float, lateral_margin_m: float, strict_depth: float,
    params: Optional[dict] = None,
) -> dict:
    """Corrige le tracé de ``result`` pour respecter l'écart minimal aux
    balises. Best-effort : toute anomalie renvoie le résultat d'origine."""
    p = merge_params(params)
    if not p["standoff_enforce"]:
        return result
    grid = get_grid()
    sm = get_seamarks()
    wps = result.get("waypoints") or []
    if grid is None or sm is None or len(wps) < 2:
        return result

    pts = [(float(w["lat"]), float(w["lng"])) for w in wps]
    la = [q[0] for q in pts]
    lo = [q[1] for q in pts]
    mlng = m_per_deg_lng((min(la) + max(la)) / 2)
    exempt = (start, requested_end)

    # Mêmes tableaux de contrôle que la passe 3 du moteur historique.
    clearance = None
    cl = sm.clearance_points(min(la) - 0.01, max(la) + 0.01,
                             min(lo) - 0.01, max(lo) + 0.01, min_depth)
    if cl:
        clearance = np.asarray(cl, dtype=np.float64)
    gates_arr = None
    ga = [
        g for g in sm.gates(min(la) - 0.01, max(la) + 0.01,
                            min(lo) - 0.01, max(lo) + 0.01)
        if not any(_d_m((g[0], g[1]), q[0], q[1], mlng) < MOORING_EXEMPT_M
                   for q in exempt)
    ]
    if ga:
        gates_arr = np.asarray(ga, dtype=np.float64)

    ctx = _Ctx(grid, min_depth, lateral_margin_m, clearance, gates_arr,
               strict_depth, mlng)

    # Balises effectivement frôlées, les plus critiques d'abord. Deux passes :
    # écarter une bouée déplace le tracé, ce qui peut libérer (ou révéler) le
    # cas de sa voisine — le score d'écartement étant monotone croissant, la
    # boucle converge.
    fixed: list[str] = []
    budget = int(p["standoff_max_marks"])
    for _round in range(2):
        circles_all = sm.standoff_circles(min(la) - 0.005, max(la) + 0.005,
                                          min(lo) - 0.005, max(lo) + 0.005)
        todo: list[tuple[float, float, float, float, str]] = []
        for (m_lat, m_lng, r_std, name) in circles_all:
            if any(_d_m((m_lat, m_lng), q[0], q[1], mlng) < p["standoff_exempt_m"]
                   for q in exempt):
                continue
            d, _i, _P = _closest_on(pts, m_lat, m_lng, mlng)
            if d < r_std - 1.0:
                todo.append((d, m_lat, m_lng, r_std, name))
        if not todo or budget <= 0:
            break
        todo.sort(key=lambda t: t[0])
        progressed = False
        for (_d0, m_lat, m_lng, r_std, name) in todo[:budget]:
            target = r_std + float(p["standoff_pad_m"])
            cand = _fix_one_mark(pts, m_lat, m_lng, target, ctx,
                                 float(p["standoff_max_detour_m"]))
            if cand is not None:
                pts = cand
                budget -= 1
                progressed = True
                if name not in fixed:
                    fixed.append(name)
        if not progressed:
            break

    if not fixed:
        return result

    # ── Reconstruction des champs dépendants de la géométrie ─────────────
    out = rebuild_result(
        result, grid, pts, min_depth=min_depth,
        lateral_margin_m=lateral_margin_m, exempt=exempt, clearance=clearance,
    )
    # Filet de sécurité : jamais de régression du profil de fond.
    old_min = result.get("min_depth_m")
    new_min = out.get("min_depth_m")
    if (new_min is not None and old_min is not None and new_min < old_min - 0.05) \
            or (new_min is not None and new_min < min_depth - 0.45):
        return result
    out["standoff_fixed"] = fixed
    return out
