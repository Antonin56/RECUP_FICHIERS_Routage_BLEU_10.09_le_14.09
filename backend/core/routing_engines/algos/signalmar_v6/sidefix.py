"""SignalMar — Post-correction « RESPECT DU CÔTÉ DES BALISES » (13/08/2026).

Module du **Moteur F** (algo ``signalmar.v6``) — le Moteur E est FIGÉ.

Bugs armateur du 13/08 (route R-20260813-144317-MX, Arradon → La Trinité) :

1. « Truie d'Arradon » (rouge, couple avec « Le Druic ») recoupée à 165 m du
   MAUVAIS côté : l'avertissement de l'audit était là, mais rien ne réparait.
   Cause mesurée : le demi-disque interdit est bien rasterisé en maille fine
   (vérifié : 165 m au nord = bloqué), mais le tronçon fautif provient d'une
   passe grossière (maille > 35 m, côté non rasterisé) jamais re-raffinée à
   cet endroit — et le semis de cercles de la passe 3 laisse des trous
   (raté mesuré à 46 m près).
2. Balises du chenal de La Trinité non respectées (N°4 frôlée à 0,7 m, N°8 à
   129 m du mauvais côté) : hors zone pilote la maille ATL100 (75-110 m)
   désarme TOUT le rasterize de côté.

CORRECTIF (même philosophie que ``signalmar_v2/standoff.py`` : géométrique,
indépendant de la maille, jamais bloquant) : après le calcul complet, chaque
latérale de direction FIABLE laissée du mauvais côté (mêmes critères que
l'audit du Moteur D) est réparée :

* d'abord par un RE-CALCUL LOCAL du tronçon fautif (A* pleine résolution sur
  une courte fenêtre, masques de côté armés — c'est la passe fine que le
  tracé n'avait jamais reçue) ;
* sinon par une insertion géométrique d'un point de passage du BON côté
  (écart recommandé + garde), re-validée fond/portes comme la passe 3.

Les frôlements résiduels (« passe à ~1 m de N°4 ») sont écartés de la même
manière, avec une validation à DEUX niveaux : seuil normal, ou seuil marée
(plancher −2,5 m) quand le tronçon d'origine était déjà EN ROUGE (complétion
d'arrivée en zone découvrante). S'il n'y a pas la place, le tracé d'origine
est conservé avec ses avertissements — aucune route n'est jamais perdue.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

import numpy as np

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
from core.routing_engines.algos.signalmar_v1 import core as v1
from core.routing_engines.algos.signalmar_v2.standoff import (
    _best_insert_index, _closest_on, _d_m, _length_m,
)
from core.routing_engines.algos.signalmar_v4 import _audit_wrong_sides
from core.seamarks import get_seamarks

logger = logging.getLogger("signalmar.routing.v6.sidefix")

Pt = tuple[float, float]

#: Paramètres surchargeables depuis le document Moteur (champ ``params``).
DEFAULT_PARAMS: dict[str, Any] = {
    "sidefix_enforce": True,
    # Garde ajoutée à l'écart recommandé (le point visé passe à r_std + pad).
    "sidefix_pad_m": 10.0,
    # Rallonge maximale acceptée pour une réparation (par balise).
    "sidefix_max_detour_m": 900.0,
    # Abords du départ / de l'arrivée DEMANDÉS : on ne déplace rien.
    "sidefix_exempt_m": 200.0,
    # Nombre de balises réparées au maximum (sécurité perf).
    "sidefix_max_marks": 6,
}

#: Mêmes constantes que l'audit du Moteur D (_INFLUENCE_M / _EXEMPT_M).
_INFLUENCE_M = 200.0


def merge_params(params: Optional[dict]) -> dict[str, Any]:
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update({k: v for k, v in params.items() if k in DEFAULT_PARAMS})
    return p


def required_side_u(sm, m: dict) -> Optional[Pt]:
    """Vecteur unitaire (est, nord) du côté où le tracé DOIT passer —
    uniquement si la direction conventionnelle est fiable (cf. audit v4)."""
    d = sm.mark_dir_confident(m)
    if d is None:
        return None
    de, dn = d
    return (dn, -de) if m["category"] == "port" else (-dn, de)


def _bbox(pts: list[Pt], pad: float = 0.01):
    la = [p[0] for p in pts]
    lo = [p[1] for p in pts]
    return min(la) - pad, max(la) + pad, min(lo) - pad, max(lo) + pad


def side_violations(
    sm, pts: list[Pt], exempt: tuple[Pt, Pt], mlng: float,
    exempt_m: float,
) -> list[tuple[float, int, dict, Pt, float]]:
    """Latérales de direction FIABLE laissées du MAUVAIS côté — mêmes
    critères que l'audit v4 : influence 200 m (plafonnée à 0,8 × écartement
    pour un couple : leçon du chenal d'Arradon, une appariée n'impose son
    côté que si le tracé emprunte la porte). Triées par distance croissante.
    Retour : (dist_m, seg_i, mark, u_requis, influence_m)."""
    lat_s, lat_n, lng_w, lng_e = _bbox(pts)
    out: list[tuple[float, int, dict, Pt, float]] = []
    for m in sm.marks:
        if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
            continue
        if not (lat_s <= m["lat"] <= lat_n and lng_w <= m["lng"] <= lng_e):
            continue
        if any(_d_m(q, m["lat"], m["lng"], mlng) < exempt_m for q in exempt):
            continue
        u = required_side_u(sm, m)
        if u is None:
            continue
        infl = _INFLUENCE_M
        pair = sm._pair_of(m)
        if pair is not None:
            gap = math.hypot((pair["lat"] - m["lat"]) * M_PER_DEG_LAT,
                             (pair["lng"] - m["lng"]) * m_per_deg_lng(m["lat"]))
            infl = min(infl, max(0.8 * gap, 40.0))
        d, i, p = _closest_on(pts, m["lat"], m["lng"], mlng)
        if d > infl:
            continue
        ve = (p[1] - m["lng"]) * mlng
        vn = (p[0] - m["lat"]) * M_PER_DEG_LAT
        if ve * u[0] + vn * u[1] > 0.0:
            continue  # bon côté
        out.append((d, i, m, u, infl))
    out.sort(key=lambda t: t[0])
    return out


def graze_violations(
    sm, pts: list[Pt], exempt: tuple[Pt, Pt], mlng: float, exempt_m: float,
) -> list[tuple[float, int, Pt, float, str]]:
    """Balises frôlées (écart < écart recommandé adaptatif) — mêmes rayons
    que ``standoff_circles`` (SIDE_ABSOLUTE armé par l'appelant)."""
    lat_s, lat_n, lng_w, lng_e = _bbox(pts, pad=0.005)
    out: list[tuple[float, int, Pt, float, str]] = []
    for (m_lat, m_lng, r_std, name) in sm.standoff_circles(lat_s, lat_n, lng_w, lng_e):
        if any(_d_m(q, m_lat, m_lng, mlng) < exempt_m for q in exempt):
            continue
        d, i, _p = _closest_on(pts, m_lat, m_lng, mlng)
        if d < r_std - 1.0:
            out.append((d, i, (m_lat, m_lng), r_std, name))
    out.sort(key=lambda t: t[0])
    return out


class _Validator:
    """Validation de couloir à DEUX niveaux : seuil normal, ou seuil marée
    (plancher −2,5 m) si le tronçon d'ORIGINE était déjà sous le seuil
    normal (complétion d'arrivée en zone découvrante — tronçons rouges)."""

    def __init__(self, grid, min_depth: float, relaxed_depth: float,
                 lateral_margin_m: float, gates_arr, strict_depth: float) -> None:
        self.grid = grid
        self.min_depth = min_depth
        self.relaxed = relaxed_depth
        self.lateral = lateral_margin_m
        self.gates = gates_arr
        self.strict = strict_depth

    def seg_ok(self, a: Pt, b: Pt, *, allow_relaxed: bool) -> bool:
        if v1._corridor_safe(self.grid, a, b, self.min_depth, self.lateral,
                             None, half_m=15.0, gates_arr=self.gates,
                             strict_depth_w=self.strict):
            return True
        if not allow_relaxed:
            return False
        return v1._corridor_safe(self.grid, a, b, self.relaxed, self.lateral,
                                 None, half_m=15.0, gates_arr=self.gates,
                                 strict_depth_w=None)

    def orig_relaxed(self, a: Pt, b: Pt) -> bool:
        """True si le tronçon d'origine échoue DÉJÀ au seuil normal (le
        remplacement a alors droit au seuil marée)."""
        return not v1._corridor_safe(self.grid, a, b, self.min_depth,
                                     self.lateral, None, half_m=15.0,
                                     gates_arr=self.gates,
                                     strict_depth_w=self.strict)


def _reroute_bracket(
    pts: list[Pt], i0: int, i1: int, mlng: float, *,
    draft_m: float, depth_margin_m: float, lateral_margin_m: float,
    tide_m: float, max_detour_m: float,
) -> Optional[list[Pt]]:
    """RE-CALCUL LOCAL du tronçon fautif [i0..i1] : A* pleine résolution sur
    une courte fenêtre — c'est la passe fine (masques de côté armés) que le
    tracé grossier n'avait jamais reçue. None si impossible/dégradé."""
    a, b = pts[i0], pts[i1]
    try:
        sub = v1.compute_route(a[0], a[1], b[0], b[1],
                               draft_m, depth_margin_m, lateral_margin_m,
                               tide_m=tide_m)
    except v1.RouteError:
        return None
    except Exception:  # noqa: BLE001 — jamais bloquant
        logger.exception("sidefix: re-calcul local en échec")
        return None
    sw = [(float(w["lat"]), float(w["lng"])) for w in (sub.get("waypoints") or [])]
    if len(sw) < 2:
        return None
    # Le sous-calcul doit rester CONTINU avec le tracé (pas d'extrémité
    # relogée par nearest_reachable).
    if (_d_m(sw[0], a[0], a[1], mlng) > 60.0
            or _d_m(sw[-1], b[0], b[1], mlng) > 60.0):
        return None
    sw[0], sw[-1] = a, b
    if _length_m(sw, mlng) - _length_m(pts[i0:i1 + 1], mlng) > max_detour_m:
        return None
    return pts[:i0] + sw + pts[i1 + 1:]


def _brackets(pts: list[Pt], seg_i: int, m_lat: float, m_lng: float,
              mlng: float, reach_m: float) -> tuple[int, int]:
    """Indices [i0, i1] encadrant la zone d'influence de la balise."""
    i0 = seg_i
    while i0 > 0 and _d_m(pts[i0], m_lat, m_lng, mlng) < reach_m:
        i0 -= 1
    i1 = min(seg_i + 1, len(pts) - 1)
    while i1 < len(pts) - 1 and _d_m(pts[i1], m_lat, m_lng, mlng) < reach_m:
        i1 += 1
    return i0, i1


def _wrong_side(m: dict, u: Pt, p: Pt, mlng: float) -> bool:
    ve = (p[1] - m["lng"]) * mlng
    vn = (p[0] - m["lat"]) * M_PER_DEG_LAT
    return ve * u[0] + vn * u[1] <= 0.0


def _side_insert(
    pts: list[Pt], m: dict, u: Pt, target: float, infl: float,
    val: _Validator, max_detour_m: float, mlng: float, pair: Optional[dict],
) -> Optional[list[Pt]]:
    """Repli géométrique : insertion d'UN point de passage du BON côté
    (milieu de porte si couple), points intérieurs du mauvais côté retirés."""
    n0 = len(pts)
    base = [p for k, p in enumerate(pts)
            if k in (0, n0 - 1)
            or not (_d_m(p, m["lat"], m["lng"], mlng) < infl * 1.3
                    and _wrong_side(m, u, p, mlng))]
    if len(base) < 2:
        return None
    len0 = _length_m(pts, mlng)
    _d, i, _P = _closest_on(base, m["lat"], m["lng"], mlng)

    def _pt(vx: float, vy: float, r: float) -> Pt:
        return (m["lat"] + (vy * r) / M_PER_DEG_LAT,
                m["lng"] + (vx * r) / mlng)

    cands: list[Pt] = []
    # Milieu de porte d'abord (couple) : c'est LE chenal.
    if pair is not None:
        gap = _d_m((pair["lat"], pair["lng"]), m["lat"], m["lng"], mlng)
        wx = ((pair["lng"] - m["lng"]) * mlng) / max(gap, 1.0)
        wy = ((pair["lat"] - m["lat"]) * M_PER_DEG_LAT) / max(gap, 1.0)
        for frac in (0.5, 0.4, 0.6):
            cands.append(_pt(wx, wy, gap * frac))
    for extra in (0.0, 30.0, 70.0):
        for ang_deg in (0.0, 25.0, -25.0, 50.0, -50.0):
            ca = math.cos(math.radians(ang_deg))
            sa = math.sin(math.radians(ang_deg))
            cands.append(_pt(u[0] * ca - u[1] * sa,
                             u[0] * sa + u[1] * ca, target + extra))

    for q in cands:
        j = _best_insert_index(base, q, mlng, i)
        cand = base[:j + 1] + [q] + base[j + 1:]
        if _length_m(cand, mlng) - len0 > max_detour_m:
            continue
        d2, _i2, p2 = _closest_on(cand, m["lat"], m["lng"], mlng)
        if d2 <= infl and _wrong_side(m, u, p2, mlng):
            continue  # toujours du mauvais côté
        allow = val.orig_relaxed(base[j], base[j + 1] if j + 1 < len(base) else base[j])
        lo = max(0, j - 1)
        hi = min(len(cand) - 1, j + 3)
        if all(val.seg_ok(cand[k], cand[k + 1], allow_relaxed=allow)
               for k in range(lo, hi)):
            return cand
    return None


def _graze_insert(
    pts: list[Pt], m_lat: float, m_lng: float, target: float,
    val: _Validator, max_detour_m: float, mlng: float,
) -> Optional[list[Pt]]:
    """Écarte le tracé d'une balise frôlée SANS changer de côté (le côté est
    imposé par le balisage) — version deux-seuils du standoff v2."""
    n0 = len(pts)
    base = [p for k, p in enumerate(pts)
            if k in (0, n0 - 1) or _d_m(p, m_lat, m_lng, mlng) >= target]
    if len(base) < 2:
        return None
    len0 = _length_m(pts, mlng)
    d, i, P = _closest_on(base, m_lat, m_lng, mlng)
    ex = (P[1] - m_lng) * mlng
    ey = (P[0] - m_lat) * M_PER_DEG_LAT
    norm = math.hypot(ex, ey)
    if norm < 1.0:
        a, b = base[i], base[i + 1]
        sx = (b[1] - a[1]) * mlng
        sy = (b[0] - a[0]) * M_PER_DEG_LAT
        sn = math.hypot(sx, sy) or 1.0
        ex, ey, norm = -sy / sn, sx / sn, 1.0
    ux, uy = ex / norm, ey / norm

    for extra in (0.0, 20.0, 50.0):
        for ang_deg in (0.0, 25.0, -25.0, 50.0, -50.0):
            ca = math.cos(math.radians(ang_deg))
            sa = math.sin(math.radians(ang_deg))
            r = target + extra
            q = (m_lat + ((ux * sa + uy * ca) * r) / M_PER_DEG_LAT,
                 m_lng + ((ux * ca - uy * sa) * r) / mlng)
            j = _best_insert_index(base, q, mlng, i)
            cand = base[:j + 1] + [q] + base[j + 1:]
            if _length_m(cand, mlng) - len0 > max_detour_m:
                continue
            d2, _i2, _p2 = _closest_on(cand, m_lat, m_lng, mlng)
            if d2 < min(target, d + 8.0) - 2.0:
                continue
            allow = val.orig_relaxed(base[j],
                                     base[j + 1] if j + 1 < len(base) else base[j])
            lo = max(0, j - 1)
            hi = min(len(cand) - 1, j + 3)
            if all(val.seg_ok(cand[k], cand[k + 1], allow_relaxed=allow)
                   for k in range(lo, hi)):
                return cand
    return None


def _turn_angle_deg(pts: list[Pt], i: int, mlng: float) -> float:
    v1x = (pts[i][1] - pts[i - 1][1]) * mlng
    v1y = (pts[i][0] - pts[i - 1][0]) * M_PER_DEG_LAT
    v2x = (pts[i + 1][1] - pts[i][1]) * mlng
    v2y = (pts[i + 1][0] - pts[i][0]) * M_PER_DEG_LAT
    n1 = math.hypot(v1x, v1y)
    n2 = math.hypot(v2x, v2y)
    if n1 < 1.0 or n2 < 1.0:
        return 0.0
    cos = (v1x * v2x + v1y * v2y) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _seg_marks_ok(sm, a: Pt, c: Pt, mlng: float,
                  exempt: tuple[Pt, Pt], exempt_m: float) -> bool:
    """True si le segment direct a→c ne crée ni frôlement ni mauvais côté."""
    lat_s, lat_n = min(a[0], c[0]) - 0.005, max(a[0], c[0]) + 0.005
    lng_w, lng_e = min(a[1], c[1]) - 0.005, max(a[1], c[1]) + 0.005
    for (m_lat, m_lng2, r_std, _name) in sm.standoff_circles(
            lat_s, lat_n, lng_w, lng_e):
        if any(_d_m(q, m_lat, m_lng2, mlng) < exempt_m for q in exempt):
            continue
        d, _i, _p = _closest_on([a, c], m_lat, m_lng2, mlng)
        if d < r_std - 1.0:
            return False
    for m in sm.marks:
        if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
            continue
        if not (lat_s <= m["lat"] <= lat_n and lng_w <= m["lng"] <= lng_e):
            continue
        if any(_d_m(q, m["lat"], m["lng"], mlng) < exempt_m for q in exempt):
            continue
        u = required_side_u(sm, m)
        if u is None:
            continue
        infl = _INFLUENCE_M
        pair = sm._pair_of(m)
        if pair is not None:
            gap = math.hypot((pair["lat"] - m["lat"]) * M_PER_DEG_LAT,
                             (pair["lng"] - m["lng"]) * m_per_deg_lng(m["lat"]))
            infl = min(infl, max(0.8 * gap, 40.0))
        d, _i, p = _closest_on([a, c], m["lat"], m["lng"], mlng)
        if d <= infl and _wrong_side(m, u, p, mlng):
            return False
    return True


def _smooth_hairpins(
    pts: list[Pt], sm, val: _Validator, mlng: float,
    exempt: tuple[Pt, Pt], exempt_m: float, max_removals: int = 10,
) -> tuple[list[Pt], int]:
    """13/08 (« trajectoire en Z non justifiée ») — retire les ÉPINGLES
    (virage > 100°) quand le segment direct est sûr (fond deux-seuils,
    portes) ET ne crée ni frôlement ni mauvais côté. Les points
    incontournables sont gelés — jamais bloquant."""
    removed = 0
    frozen: set[Pt] = set()
    while removed < max_removals:
        worst_i, worst_ang = -1, 100.0
        for i in range(1, len(pts) - 1):
            if pts[i] in frozen:
                continue
            ang = _turn_angle_deg(pts, i, mlng)
            if ang > worst_ang:
                worst_ang, worst_i = ang, i
        if worst_i < 0:
            break
        i = worst_i
        a, c = pts[i - 1], pts[i + 1]
        allow = (val.orig_relaxed(pts[i - 1], pts[i])
                 or val.orig_relaxed(pts[i], pts[i + 1]))
        if (val.seg_ok(a, c, allow_relaxed=allow)
                and _seg_marks_ok(sm, a, c, mlng, exempt, exempt_m)):
            pts = pts[:i] + pts[i + 1:]
            removed += 1
        else:
            frozen.add(pts[i])
    return pts, removed


def enforce_mark_sides(
    result: dict, *,
    start: Pt, requested_end: Pt,
    draft_m: float, depth_margin_m: float, lateral_margin_m: float,
    tide_m: float, min_depth: float, relaxed_depth: float,
    strict_depth: float, base_need: float,
    params: Optional[dict] = None,
) -> dict:
    """Répare les MAUVAIS CÔTÉS puis les FRÔLEMENTS du tracé final.
    Best-effort : toute anomalie renvoie le résultat d'origine."""
    p = merge_params(params)
    if not p["sidefix_enforce"]:
        return result
    grid = v1.get_grid()
    sm = get_seamarks()
    wps = result.get("waypoints") or []
    if grid is None or sm is None or len(wps) < 2:
        return result

    pts: list[Pt] = [(float(w["lat"]), float(w["lng"])) for w in wps]
    lat_s, lat_n, lng_w, lng_e = _bbox(pts)
    mlng = m_per_deg_lng((lat_s + lat_n) / 2)
    exempt = (start, requested_end)
    exempt_m = float(p["sidefix_exempt_m"])
    max_detour = float(p["sidefix_max_detour_m"])
    pad = float(p["sidefix_pad_m"])

    gates_arr = None
    ga = [g for g in sm.gates(lat_s, lat_n, lng_w, lng_e)
          if not any(_d_m((g[0], g[1]), q[0], q[1], mlng) < 400.0
                     for q in exempt)]
    if ga:
        gates_arr = np.asarray(ga, dtype=np.float64)
    val = _Validator(grid, min_depth, relaxed_depth, lateral_margin_m,
                     gates_arr, strict_depth)

    fixed: list[str] = []
    budget = int(p["sidefix_max_marks"])

    # ── 1. MAUVAIS CÔTÉS (priorité armateur : le balisage prime) ─────────
    for _round in range(2):
        viols = side_violations(sm, pts, exempt, mlng, exempt_m)
        if not viols or budget <= 0:
            break
        progressed = False
        for (_d0, seg_i, m, u, infl) in viols[:budget]:
            name = m.get("name") or f"latérale {m['category']}"
            i0, i1 = _brackets(pts, seg_i, m["lat"], m["lng"], mlng,
                               infl + 120.0)
            cand = None
            if i1 > i0:
                cand = _reroute_bracket(
                    pts, i0, i1, mlng,
                    draft_m=draft_m, depth_margin_m=depth_margin_m,
                    lateral_margin_m=lateral_margin_m, tide_m=tide_m,
                    max_detour_m=max_detour)
                if cand is not None:
                    d2, _i2, p2 = _closest_on(cand, m["lat"], m["lng"], mlng)
                    if d2 <= infl and _wrong_side(m, u, p2, mlng):
                        cand = None  # toujours fautif : repli géométrique
            if cand is None:
                r_std = min(60.0, max(0.35 * sm._nearest_lateral_m(m), 25.0))
                cand = _side_insert(pts, m, u, r_std + pad, infl, val,
                                    max_detour, mlng, sm._pair_of(m))
            if cand is not None:
                pts = cand
                budget -= 1
                progressed = True
                if name not in fixed:
                    fixed.append(name)
        if not progressed:
            break

    # ── 2. FRÔLEMENTS résiduels (écart minimal, deux seuils) ─────────────
    for _round in range(2):
        grz = graze_violations(sm, pts, exempt, mlng, exempt_m)
        if not grz or budget <= 0:
            break
        progressed = False
        for (_d0, _seg_i, (m_lat, m_lng), r_std, name) in grz[:budget]:
            cand = _graze_insert(pts, m_lat, m_lng, r_std + pad, val,
                                 max_detour, mlng)
            if cand is not None:
                pts = cand
                budget -= 1
                progressed = True
                if name not in fixed:
                    fixed.append(name)
        if not progressed:
            break

    # ── 3. LISSAGE des épingles (« trajectoire en Z non justifiée ») ─────
    pts, n_smooth = _smooth_hairpins(pts, sm, val, mlng, exempt, exempt_m)

    if not fixed and not n_smooth:
        return result

    # ── Reconstruction des champs dépendants de la géométrie ─────────────
    new_wps = [{"lat": round(q[0], 6), "lng": round(q[1], 6)} for q in pts]
    fresh = v1._result_for(grid, new_wps, min_depth)
    old_min = result.get("min_depth_m")
    new_min = fresh.get("min_depth_m")
    if (new_min is not None and old_min is not None
            and new_min < old_min - 0.05):
        return result  # jamais de régression du profil de fond

    out = dict(result)
    out["waypoints"] = fresh["waypoints"]
    out["distance_m"] = fresh["distance_m"]
    out["min_depth_m"] = fresh["min_depth_m"]
    out["depth_profile"] = fresh["depth_profile"]
    clearance = None
    cl = sm.clearance_points(lat_s, lat_n, lng_w, lng_e, min_depth)
    if cl:
        clearance = np.asarray(cl, dtype=np.float64)
    out["corridor_m"] = v1._corridors_for(grid, new_wps, min_depth,
                                          lateral_margin_m, clearance)
    comp = [i for i in v1.shallow_legs(new_wps, base_need)]
    if comp:
        out["compromised_legs"] = comp
        out["risk"] = True
    else:
        out.pop("compromised_legs", None)
        out["risk"] = False
    # Avertissements : purge de ceux qui dépendent du tracé, puis ré-audit.
    kept = [w for w in (result.get("warnings") or [])
            if not w.startswith("⚠ MAUVAIS CÔTÉ DE BALISE")
            and not w.startswith("⚠ La route passe à ~")
            and not w.startswith("Passage à ")]
    kept.extend(fresh.get("warnings") or [])
    kept.extend(v1._mark_pass_audit(new_wps, exempt))
    out["warnings"] = list(dict.fromkeys(kept))
    out.pop("wrong_side_marks", None)
    _audit_wrong_sides(out, start, requested_end)
    out["sidefix_applied"] = fixed
    return out


__all__ = ["DEFAULT_PARAMS", "enforce_mark_sides", "side_violations",
           "graze_violations", "required_side_u"]
