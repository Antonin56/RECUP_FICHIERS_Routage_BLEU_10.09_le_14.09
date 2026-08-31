"""SignalMar — MOTEUR I (27/08/2026) : moteur de TRAVAIL, duplicata du Moteur F gelé.

Créé par duplication à l'identique de ``core/nav/engine_f_frozen.py``
(ordre armateur du 27/08/2026). C'est ICI — et uniquement ici — que se font
désormais toutes les améliorations et corrections de routage. Le Moteur F
(``engine_f_frozen.py``) est la référence immuable de non-régression :
au moment de la création, les deux moteurs rendent des résultats
STRICTEMENT identiques.

Contenu : section 1 = sidefix (post-correction du côté des balises),
section 2 = classe moteur (``EngineI``, algo ``signalmar.i``, base
SignalmarV5 figée).
"""
from __future__ import annotations

# ════════════════════════════════════════════════════════════════════════
# SECTION 1/2 — copie intégrale de signalmar_v6/sidefix.py (13-27/08/2026)
# ════════════════════════════════════════════════════════════════════════
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
from core.seamarks import DIR_COHERENCE_V6, LATERAL_AUTHORITY_M, get_seamarks

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
    "sidefix_max_marks": 10,
}

#: Mêmes constantes que l'audit du Moteur D (_INFLUENCE_M / _EXEMPT_M).
_INFLUENCE_M = 200.0


def pair_influence(sm, m: dict) -> float:
    """Portée d'imposition du côté d'une latérale. 25/08 (bug Lorient « La
    Petite Jument » : MAUVAIS côté à 93 m, ancien plafond 0,8 × couple =
    85 m → jamais réparée) : pour un couple, plafond relevé à
    min(200, max(1,2 × écartement, 80)) — passer juste À CÔTÉ de la porte du
    mauvais côté est bien une faute de balisage."""
    infl = _INFLUENCE_M
    pair = sm._pair_of(m)
    if pair is not None:
        gap = math.hypot((pair["lat"] - m["lat"]) * M_PER_DEG_LAT,
                         (pair["lng"] - m["lng"]) * m_per_deg_lng(m["lat"]))
        if DIR_COHERENCE_V6.get():
            infl = min(infl, max(1.2 * gap, 80.0))
        else:  # comportement Moteur F validé (audit v4)
            infl = min(infl, max(0.8 * gap, 40.0))
    # 25/08 — direction HÉRITÉE du voisinage (pas de signal propre) : portée
    # réduite, on n'impose pas un chenal secondaire à une route qui passe au
    # large (A6/A8/M6 de Kernevel).
    if m.get("_dir_v6_inferred"):
        infl = min(infl, 120.0)
    return infl


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
        infl = pair_influence(sm, m)
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
    sm=None, exempt: Optional[tuple[Pt, Pt]] = None, exempt_m: float = 200.0,
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
    # 25/08 — hors zone pilote (maille ATL100 > 35 m) le sous-A* n'applique
    # PAS les côtés : le sous-tracé ne doit créer AUCUNE nouvelle infraction
    # de balisage (mauvais côté / frôlement), sinon repli géométrique.
    if sm is not None and exempt is not None and DIR_COHERENCE_V6.get():
        if not all(_seg_marks_ok(sm, sw[k], sw[k + 1], mlng, exempt, exempt_m,
                                 repair_mode=True, ref=pts)
                   for k in range(len(sw) - 1)):
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
    sm=None, exempt: Optional[tuple[Pt, Pt]] = None, exempt_m: float = 200.0,
) -> Optional[list[Pt]]:
    """Repli géométrique : insertion d'UN point de passage du BON côté
    (milieu de porte si couple), points intérieurs du mauvais côté retirés.

    26/08 (bug Lorient : « N° 3 »/« Banc du Turc » jamais réparées) : la
    fenêtre de validation englobait des segments INCHANGÉS du tracé (dont un
    segment d'arrivée déjà « rouge ») → tous les candidats étaient rejetés
    au fond. Un segment identique au tracé courant ne peut pas créer de
    régression : il n'est plus re-validé."""
    n0 = len(pts)
    cur_segs = {(pts[k], pts[k + 1]) for k in range(n0 - 1)}
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
        a0 = base[j]
        b0 = base[j + 1] if j + 1 < len(base) else base[j]
        variants: list[tuple[list[Pt], int]] = [
            (base[:j + 1] + [q] + base[j + 1:], 1)]
        # 26/08 (bug Lorient « Écrevisse ») — sur un LONG bord, insérer q
        # seul fait pivoter tout le bord (3,5 km) et peut le rapprocher
        # d'un danger lointain. Variante « épinglée » : le bord garde sa
        # ligne d'origine sauf aux abords de la balise (± 300 m).
        seg_len = _d_m(a0, b0[0], b0[1], mlng)
        if seg_len > 900.0:
            sx = (b0[1] - a0[1]) * mlng
            sy = (b0[0] - a0[0]) * M_PER_DEG_LAT
            qx = (q[1] - a0[1]) * mlng
            qy = (q[0] - a0[0]) * M_PER_DEG_LAT
            t = max(0.0, min(seg_len, (qx * sx + qy * sy) / max(seg_len, 1.0)))
            mid: list[Pt] = []
            for tt in (t - 300.0, None, t + 300.0):
                if tt is None:
                    mid.append(q)
                elif 50.0 < tt < seg_len - 50.0:
                    f = tt / seg_len
                    mid.append((a0[0] + (b0[0] - a0[0]) * f,
                                a0[1] + (b0[1] - a0[1]) * f))
            if len(mid) > 1:
                variants.append((base[:j + 1] + mid + base[j + 1:], len(mid)))

        for cand, ins_n in variants:
            if _length_m(cand, mlng) - len0 > max_detour_m:
                continue
            d2, _i2, p2 = _closest_on(cand, m["lat"], m["lng"], mlng)
            if d2 <= infl and _wrong_side(m, u, p2, mlng):
                continue  # toujours du mauvais côté
            allow = val.orig_relaxed(a0, b0)
            lo = max(0, j - 1)
            hi = min(len(cand) - 1, j + 2 + ins_n)
            changed = [k for k in range(lo, hi)
                       if (cand[k], cand[k + 1]) not in cur_segs]
            if not all(val.seg_ok(cand[k], cand[k + 1], allow_relaxed=allow)
                       for k in changed):
                continue
            # aucune NOUVELLE infraction de balisage (segments modifiés)
            if sm is not None and exempt is not None and DIR_COHERENCE_V6.get():
                others_ok = all(
                    _seg_marks_ok(sm, cand[k], cand[k + 1], mlng, exempt,
                                  exempt_m, ignore=m, repair_mode=True,
                                  ref=pts)
                    for k in changed)
                if not others_ok:
                    continue
            return cand
    return None


def _cardinal_yields_to_lateral(sm, m_lat: float, m_lng: float) -> bool:
    """26/08 (Moteur H) — True si la marque en (m_lat, m_lng) est une
    CARDINALE avec une LATÉRALE fiable dans le rayon LATERAL_AUTHORITY_M
    (le balisage de chenal prime : pas de détour imposé par la cardinale)."""
    radius = LATERAL_AUTHORITY_M.get()
    if radius <= 0.0:
        return False
    mark = None
    for m in sm.marks:
        if abs(m["lat"] - m_lat) < 1e-6 and abs(m["lng"] - m_lng) < 1e-6:
            mark = m
            break
    if mark is None or mark.get("kind") != "cardinal":
        return False
    mlng = m_per_deg_lng(m_lat)
    for o in sm.marks:
        if o.get("kind") != "lateral" or o.get("category") not in ("port", "starboard"):
            continue
        if math.hypot((o["lat"] - m_lat) * v1.M_PER_DEG_LAT,
                      (o["lng"] - m_lng) * mlng) > radius:
            continue
        if sm.mark_dir_confident(o) is not None:
            return True
    return False


def _graze_insert(
    pts: list[Pt], m_lat: float, m_lng: float, target: float,
    val: _Validator, max_detour_m: float, mlng: float,
) -> Optional[list[Pt]]:
    """Écarte le tracé d'une balise frôlée SANS changer de côté (le côté est
    imposé par le balisage) — version deux-seuils du standoff v2.
    26/08 : segments inchangés jamais re-validés (cf. _side_insert)."""
    n0 = len(pts)
    cur_segs = {(pts[k], pts[k + 1]) for k in range(n0 - 1)}
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
            if all((cand[k], cand[k + 1]) in cur_segs
                   or val.seg_ok(cand[k], cand[k + 1], allow_relaxed=allow)
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
                  exempt: tuple[Pt, Pt], exempt_m: float,
                  ignore: Optional[dict] = None,
                  repair_mode: bool = False,
                  ref: Optional[list[Pt]] = None) -> bool:
    """True si le segment direct a→c ne crée ni frôlement ni mauvais côté.

    26/08 — ``ref`` (tracé COURANT) : une gêne DÉJÀ présente sur le tracé
    d'origine (ex. épave frôlée à 38 m sur un long bord inchangé en
    direction) ne bloque pas la réparation — seule une infraction NOUVELLE
    compte (bug Lorient « Écrevisse » jamais réparée)."""

    def _preexisting(o_lat: float, o_lng: float, thresh: float) -> bool:
        if ref is None:
            return False
        d0, _i0, _p0 = _closest_on(ref, o_lat, o_lng, mlng)
        return d0 < thresh

    lat_s, lat_n = min(a[0], c[0]) - 0.005, max(a[0], c[0]) + 0.005
    lng_w, lng_e = min(a[1], c[1]) - 0.005, max(a[1], c[1]) + 0.005
    for (m_lat, m_lng2, r_std, _name) in sm.standoff_circles(
            lat_s, lat_n, lng_w, lng_e):
        if any(_d_m(q, m_lat, m_lng2, mlng) < exempt_m for q in exempt):
            continue
        d, _i, _p = _closest_on([a, c], m_lat, m_lng2, mlng)
        thr = 0.6 * r_std if repair_mode else r_std - 1.0
        if d < thr and not _preexisting(m_lat, m_lng2, thr):
            return False
    for m in sm.marks:
        if m is ignore:
            continue
        if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
            continue
        if not (lat_s <= m["lat"] <= lat_n and lng_w <= m["lng"] <= lng_e):
            continue
        if any(_d_m(q, m["lat"], m["lng"], mlng) < exempt_m for q in exempt):
            continue
        u = required_side_u(sm, m)
        if u is None:
            continue
        infl = pair_influence(sm, m)
        if repair_mode:
            # en réparation, seule la création d'un FRÔLEMENT est bloquante
            # ici : les côtés sont re-contrôlés globalement (tours suivants
            # + garde-fou net final).
            continue
        d, _i, p = _closest_on([a, c], m["lat"], m["lng"], mlng)
        if d <= infl and _wrong_side(m, u, p, mlng):
            return False
    # 25/08 (mode cohérence chenaux uniquement) — le segment direct ne doit
    # pas traverser un champ de mouillage ni frôler un danger.
    if not DIR_COHERENCE_V6.get():
        return True
    la_c, lo_c = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
    for mo in sm.moorings:
        if abs(mo["lat"] - la_c) > 0.02 or abs(mo["lng"] - lo_c) > 0.03:
            continue
        d, _i, _p = _closest_on([a, c], mo["lat"], mo["lng"], mlng)
        if d < 45.0 and not _preexisting(mo["lat"], mo["lng"], 45.0):
            return False
    for h in sm.hazards:
        if abs(h["lat"] - la_c) > 0.02 or abs(h["lng"] - lo_c) > 0.03:
            continue
        d, _i, _p = _closest_on([a, c], h["lat"], h["lng"], mlng)
        if d < 40.0 and not _preexisting(h["lat"], h["lng"], 40.0):
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
        worst_i, worst_ang = -1, 0.0
        for i in range(1, len(pts) - 1):
            if pts[i] in frozen:
                continue
            ang = _turn_angle_deg(pts, i, mlng)
            # 25/08 (« virages droite puis gauche injustifiés » après Grand
            # Mouton) — en plus des épingles (> 100°), les CROCHETS locaux
            # (> 60° entre deux segments courts < 500 m) sont candidats.
            local = (DIR_COHERENCE_V6.get() and ang > 60.0
                     and _d_m(pts[i], pts[i - 1][0], pts[i - 1][1], mlng) < 500.0
                     and _d_m(pts[i], pts[i + 1][0], pts[i + 1][1], mlng) < 500.0)
            if (ang > 100.0 or local) and ang > worst_ang:
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
    budget = int(p["sidefix_max_marks"]) if DIR_COHERENCE_V6.get() else 6

    # 26/08 (bug Lorient : réparations INTERDÉPENDANTES) — écarter une
    # balise frôlée (phase 2) peut débloquer la réparation d'un mauvais
    # côté voisin (phase 1, ex. « N° 3 » puis « Banc du Turc ») : les deux
    # phases sont rejouées une seconde fois en mode cohérence chenaux.
    for _pass in range(2 if DIR_COHERENCE_V6.get() else 1):
        budget_at_pass = budget

        # ── 1. MAUVAIS CÔTÉS (priorité armateur : le balisage prime) ─────
        for _round in range(4 if DIR_COHERENCE_V6.get() else 2):
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
                        max_detour_m=max_detour,
                        sm=sm, exempt=exempt, exempt_m=exempt_m)
                    if cand is not None:
                        d2, _i2, p2 = _closest_on(cand, m["lat"], m["lng"],
                                                  mlng)
                        if d2 <= infl and _wrong_side(m, u, p2, mlng):
                            cand = None  # toujours fautif : repli géométrique
                if cand is None:
                    r_std = min(60.0, max(0.35 * sm._nearest_lateral_m(m),
                                          25.0))
                    cand = _side_insert(pts, m, u, r_std + pad, infl, val,
                                        max_detour, mlng, sm._pair_of(m),
                                        sm=sm, exempt=exempt,
                                        exempt_m=exempt_m)
                if cand is not None:
                    pts = cand
                    budget -= 1
                    progressed = True
                    if name not in fixed:
                        fixed.append(name)
            if not progressed:
                break

        # ── 2. FRÔLEMENTS résiduels (écart minimal, deux seuils) ─────────
        for _round in range(2):
            grz = graze_violations(sm, pts, exempt, mlng, exempt_m)
            if not grz or budget <= 0:
                break
            progressed = False
            for (_d0, _seg_i, (m_lat, m_lng), r_std, name) in grz[:budget]:
                # 26/08 (Moteur H, gated LATERAL_AUTHORITY_M) — priorité au
                # balisage de chenal : une CARDINALE flanquée d'une latérale
                # fiable dans le rayon ne DÉTOURNE plus la route (le
                # frôlement reste signalé par l'audit, jamais traversée).
                if _cardinal_yields_to_lateral(sm, m_lat, m_lng):
                    continue
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

        if budget == budget_at_pass or budget <= 0:
            break  # rien réparé à cette passe : inutile de rejouer

    # ── 3. LISSAGE des épingles (« trajectoire en Z non justifiée ») ─────
    pts, n_smooth = _smooth_hairpins(pts, sm, val, mlng, exempt, exempt_m)

    if not fixed and not n_smooth:
        return result

    # ── Garde-fou NET (25/08) : le tracé réparé doit être STRICTEMENT
    # meilleur (score = mauvais côtés + frôlements, frôlement < 25 m compte
    # double). Sinon, résultat d'origine conservé tel quel.
    def _score(pp: list[Pt]) -> int:
        sc = 0
        for (_d, _i, _m, _u, _infl) in side_violations(sm, pp, exempt, mlng, exempt_m):
            sc += 1
        for (dd, _i, _mm, _rs, _n) in graze_violations(sm, pp, exempt, mlng, exempt_m):
            sc += 2 if dd < 25.0 else 1
        return sc

    orig_pts = [(float(w["lat"]), float(w["lng"])) for w in wps]
    if DIR_COHERENCE_V6.get() and fixed and _score(pts) >= _score(orig_pts):
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


# ════════════════════════════════════════════════════════════════════════
# SECTION 2/2 — copie intégrale de signalmar_v6/__init__.py (classe moteur)
# ════════════════════════════════════════════════════════════════════════
"""SignalMar — Algo « signalmar.v6 » (MOTEUR F, base Moteur E, 13/08/2026).

Consigne armateur du 13/08 : « Le Moteur E est le meilleur. Tu le copies pour
créer le Moteur F, et tu VERROUILLES le Moteur E. » Le Moteur E (signalmar.v5,
5.1.0) est donc FIGÉ à cette date — plus aucune modification de son code ni
de ses chemins gardés par ``SIDE_ABSOLUTE``.

v6 = v5 + les corrections du 13/08 (bugs armateur, route
R-20260813-144317-MX Arradon → La Trinité), gardées par le contextvar
``SIDE_ABSOLUTE_V6`` et par des surcharges LOCALES à cette classe — les
Moteurs A/B/C/D/E restent STRICTEMENT inchangés :

1. **RESPECT DU CÔTÉ garanti** (« Truie d'Arradon » recoupée à 165 m du
   mauvais côté MALGRÉ l'avertissement) : post-correction géométrique
   ``enforce_mark_sides`` — chaque latérale fiable laissée du
   mauvais côté est réparée (re-calcul local pleine résolution, sinon point
   de passage du bon côté), puis les frôlements résiduels sont écartés
   (« passe à ~1 m de N°4 »). Indépendant de la maille, jamais bloquant.
2. **Complétion d'arrivée disciplinée** (balises du chenal de La Trinité
   non respectées) : si l'extension A* (marée +6 m) laisse une latérale
   fiable du mauvais côté ou frôle une balise, elle est REMPLACÉE par le
   suivi du chenal balisé (le balisage PRIME sur la donnée de fond).
3. **Arrivée réellement atteinte** : le reliquat est désormais MESURÉ
   géométriquement (l'extension pouvait s'arrêter à un nœud de grille à
   ~100 m du point demandé sans le signaler).
"""

import logging
import math
from typing import Any

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
from core.routing_engines.algos.signalmar_v1 import core as _v1
from core.routing_engines.algos.signalmar_v2.standoff import _closest_on, _d_m
from core.routing_engines.algos.signalmar_v4 import SignalmarV4
from core.routing_engines.algos.signalmar_v5 import (
    SignalmarV5, _COMPLETE_MIN_M, _DONE_M,
)
from core.seamarks import (
    DIR_COHERENCE_V6, RASTER_CACHE, SIDE_ABSOLUTE, SIDE_ABSOLUTE_V6,
    get_seamarks,
)

logger = logging.getLogger("signalmar.routing.v6")

# 14/08/2026 (audit QA P0/FND-004) — au-delà de cette « profondeur » (fond
# à plus de 3,5 m AU-DESSUS du zéro hydro), ce n'est plus une zone
# découvrante mais la TERRE FERME : aucun tronçon de route n'a le droit d'y
# être tracé, quelle que soit la marée.
_LAND_LIMIT_M = -3.5


class EngineI(SignalmarV5):
    id = "signalmar.i"
    version = "7.0.0"
    description = (
        "Moteur I (base Moteur F gelé au 27.08.26) : routes OFFICIELLES "
        "prioritaires ÉCRÊTÉES AU TIRANT D'EAU RÉEL (un pointillé qui "
        "traverse un fond insuffisant — banc du Turc — est coupé et le "
        "raccord recalculé), doublons de balises contradictoires "
        "neutralisés (« Les Errants »), respect du côté des balises "
        "garanti, arrivée réellement atteinte. Moteurs A-H inchangés."
    )

    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        """MOTEUR I (GO armateur 31/08/2026) : routes OFFICIELLES prioritaires
        (logique Moteur H) mais réseau ÉCRÊTÉ AU BESOIN D'EAU RÉEL du bateau
        (tirant + marge − marée, plancher 0,5 m au ZH — cf. section 3) : le
        pointillé qui traverse un fond insuffisant (banc du Turc à tirant
        1,5 m) est coupé, le raccord contourne par le calcul classique.
        Aucune route officielle exploitable → calcul Moteur F intégral."""
        p = dict(params or {})
        p.setdefault("dir_coherence", True)          # faux couples corrigés
        radius = float(p.get("chenal_radius_m", 1000.0))
        attach = float(p.get("track_attach_m", 3000.0))
        clip = max(float(draft_m) + float(depth_margin_m) - float(tide_m),
                   _MIN_CLIP_M)
        # Contextvars armés sur TOUTE la durée (audit final du tracé assemblé
        # compris) — mêmes gardes que le Moteur H ; _compute_base les
        # ré-arme en imbriqué (sans effet, mêmes valeurs).
        tokl = LATERAL_AUTHORITY_M.set(max(radius, 0.0))
        tok5 = SIDE_ABSOLUTE.set(True)
        tok6v = SIDE_ABSOLUTE_V6.set(True)
        tokdv = DIR_COHERENCE_V6.set(True)
        try:
            plan: list[dict] = []
            try:
                plan = _plan_tracks_i(
                    (start_lat, start_lng), (end_lat, end_lng), attach,
                    float(p.get("track_bias", 1.4)), clip)
            except Exception:                        # noqa: BLE001
                logger.exception("i: plan routes officielles en échec — repli F")
            if plan:
                try:
                    res = self._compute_with_tracks(
                        plan, start_lat, start_lng, end_lat, end_lng,
                        draft_m, depth_margin_m, lateral_margin_m,
                        tide_m, clip, p)
                    _strip_suspect_wrong_sides(res)
                    return res
                except _v1.RouteError:
                    raise
                except Exception:                    # noqa: BLE001
                    logger.exception(
                        "i: assemblage routes officielles en échec — repli F")
            res = self._compute_base(
                start_lat, start_lng, end_lat, end_lng,
                draft_m, depth_margin_m, lateral_margin_m,
                tide_m=tide_m, params=p)
            _strip_suspect_wrong_sides(res)
            return res
        finally:
            DIR_COHERENCE_V6.reset(tokdv)
            SIDE_ABSOLUTE_V6.reset(tok6v)
            SIDE_ABSOLUTE.reset(tok5)
            LATERAL_AUTHORITY_M.reset(tokl)

    # ── Assemblage : raccords _compute_base + tronçons « route officielle »
    def _compute_with_tracks(
        self, plan: list[dict],
        start_lat: float, start_lng: float, end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float, clip_m: float, p: dict[str, Any],
    ) -> dict:
        """Copie de l'assemblage du Moteur H (signalmar_h, inchangé) : legs
        de raccord par le moteur classique + tronçons calés sur les
        pointillés ÉCRÊTÉS, résultat (profil, distance, tronçons rouges,
        audits) recalculé sur le tracé assemblé."""
        merged: list[dict] = []
        warnings: list[str] = []
        risk = False
        compromised: list[int] = []
        used_names: list[str] = []

        def _extend(wps: list[dict]) -> None:
            for w in wps:
                q = {"lat": round(float(w["lat"]), 6),
                     "lng": round(float(w["lng"]), 6)}
                if merged and merged[-1] == q:
                    continue
                merged.append(q)

        def _leg(a: tuple[float, float], b: tuple[float, float]) -> dict | None:
            if _sr._d_m(a, b) < _LEG_SKIP_I_M:
                return None
            return self._compute_base(
                a[0], a[1], b[0], b[1],
                draft_m, depth_margin_m, lateral_margin_m,
                tide_m=tide_m, params=p)

        cur = (start_lat, start_lng)
        for path in plan:
            entry = path["pts"][0]
            leg = _leg(cur, entry)
            if leg:
                n0 = len(merged)
                _extend(leg.get("waypoints") or [])
                risk |= bool(leg.get("risk"))
                compromised += [n0 + i for i in (leg.get("compromised_legs") or [])]
            _extend([{"lat": q[0], "lng": q[1]} for q in path["pts"]])
            used_names += [n for n in path["names"] if n not in used_names]
            cur = path["pts"][-1]
        leg = _leg(cur, (end_lat, end_lng))
        end_snapped = None
        if leg:
            n0 = len(merged)
            _extend(leg.get("waypoints") or [])
            risk |= bool(leg.get("risk"))
            compromised += [n0 + i for i in (leg.get("compromised_legs") or [])]
            if leg.get("end_snapped"):
                end_snapped = leg["end_snapped"]
            for w in (leg.get("warnings") or []):
                if w.startswith("⚠ ARRIVÉE") or w.startswith("⚠ FIN DE ROUTE"):
                    warnings.append(w)
        else:
            _extend([{"lat": end_lat, "lng": end_lng}])
        if len(merged) < 2:
            raise _v1.RouteError("Route officielle inexploitable.")

        # Résultat complet recalculé sur le tracé assemblé (profil, distance,
        # tronçons rouges) + audits balises du tracé FINAL.
        need = max(draft_m + depth_margin_m - tide_m, -2.5)
        grid = _v1.get_grid()
        res: dict[str, Any] = {"waypoints": merged}
        if grid is not None:
            res.update(_v1._result_for(grid, merged, need))
        comp = sorted(set(compromised)
                      | set(_v1.shallow_legs(merged, need) if grid is not None else []))
        if comp:
            res["compromised_legs"] = comp
            risk = True
        if risk:
            res["risk"] = True
        if end_snapped:
            res["end_snapped"] = end_snapped
        track_label = ", ".join(f"« {n} »" for n in used_names[:3]) or "officielle"
        res["official_tracks"] = used_names
        res["warnings"] = [
            f"Route calée sur la route officielle {track_label} "
            f"(pointillés de la carte), écrêtée à votre besoin d'eau "
            f"({clip_m:.1f} m au zéro hydro)."] + warnings
        res["warnings"].extend(_v1._mark_pass_audit(
            merged, ((start_lat, start_lng), (end_lat, end_lng))))
        res["warnings"] = list(dict.fromkeys(res["warnings"]))
        _audit_wrong_sides(res, (start_lat, start_lng), (end_lat, end_lng))
        return res

    def _compute_base(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        tok6 = SIDE_ABSOLUTE_V6.set(True)
        # SIDE_ABSOLUTE armé sur TOUTE la durée (post-passes incluses) :
        # rayons adaptatifs + caches v5 pour l'audit et les réparations.
        tok5 = SIDE_ABSOLUTE.set(True)
        # 25/08 — règles de cohérence des chenaux (faux couples, héritage de
        # direction, influence 1,2 × couple, lissage 60°) : UNIQUEMENT si le
        # moteur les demande (params.dir_coherence — Moteur G).
        tokd = DIR_COHERENCE_V6.set(bool((params or {}).get("dir_coherence")))
        # 27/08/2026 (perf « route < 10 s ») — cache de rasterisation pour la
        # durée de CE calcul (les réparations sidefix relancent des
        # compute_route locaux sur les mêmes fenêtres). Gated : A-E intacts.
        tokr = RASTER_CACHE.set({})
        try:
            res = super().compute_auto(
                start_lat, start_lng, end_lat, end_lng,
                draft_m, depth_margin_m, lateral_margin_m,
                tide_m=tide_m, params=params,
            )
            # Mêmes bornes/dérivées que le moteur (cf. v2.compute_auto).
            draft = float(min(max(draft_m, _v1.DRAFT_MIN), _v1.DRAFT_MAX))
            marg = float(min(max(depth_margin_m, _v1.DEPTH_MARGIN_MIN),
                             _v1.DEPTH_MARGIN_MAX))
            lat_m = float(min(max(lateral_margin_m, _v1.LATERAL_MIN),
                              _v1.LATERAL_MAX))
            tide = float(min(max(tide_m, -2.0), 6.0))
            try:
                res = enforce_mark_sides(
                    res,
                    start=(start_lat, start_lng),
                    requested_end=(end_lat, end_lng),
                    draft_m=draft_m, depth_margin_m=depth_margin_m,
                    lateral_margin_m=lat_m, tide_m=tide,
                    min_depth=max(draft + marg - tide, -2.5),
                    relaxed_depth=max(draft + marg - 6.0, -2.5),
                    strict_depth=draft + marg + 2.0,
                    base_need=max(draft + marg, -2.5),
                    params=params,
                )
            except Exception:  # noqa: BLE001 — jamais bloquant
                logger.exception("v6: sidefix en échec, résultat rendu tel quel")
        finally:
            RASTER_CACHE.reset(tokr)
            DIR_COHERENCE_V6.reset(tokd)
            SIDE_ABSOLUTE.reset(tok5)
            SIDE_ABSOLUTE_V6.reset(tok6)
        return res

    def compute_manual(self, *args: Any, **kwargs: Any) -> dict:
        # Route MANUELLE : jamais déplacée (intention explicite) — audit v5.
        tok = SIDE_ABSOLUTE_V6.set(True)
        try:
            return super().compute_manual(*args, **kwargs)
        finally:
            SIDE_ABSOLUTE_V6.reset(tok)

    # ── Complétion d'arrivée v6 (surcharge de la v5, Moteur E figé) ──────
    @staticmethod
    def _ext_violates(ext_w: list[dict], req_end: tuple[float, float]) -> bool:
        """True si l'extension A* enfreint la discipline du chenal : latérale
        FIABLE laissée du mauvais côté (≤ 250 m — on est DANS le chenal
        d'arrivée, le balisage prime) ou balise nettement frôlée
        (< 0,6 × écart recommandé)."""
        sm = get_seamarks()
        if sm is None or len(ext_w) < 2:
            return False
        pts = [(float(w["lat"]), float(w["lng"])) for w in ext_w]
        la = [q[0] for q in pts]
        lo = [q[1] for q in pts]
        mlng = m_per_deg_lng((min(la) + max(la)) / 2)
        exempt = (pts[0], req_end)
        for m in sm.marks:
            if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
                continue
            if not (min(la) - 0.01 <= m["lat"] <= max(la) + 0.01
                    and min(lo) - 0.01 <= m["lng"] <= max(lo) + 0.01):
                continue
            if any(_d_m(q, m["lat"], m["lng"], mlng) < 200.0 for q in exempt):
                continue
            u = required_side_u(sm, m)
            if u is None:
                continue
            d, _i, p = _closest_on(pts, m["lat"], m["lng"], mlng)
            if d <= 250.0 and _wrong_side(m, u, p, mlng):
                return True
        for (m_lat, m_lng2, r_std, _name) in sm.standoff_circles(
                min(la) - 0.005, max(la) + 0.005,
                min(lo) - 0.005, max(lo) + 0.005):
            if any(_d_m(q, m_lat, m_lng2, mlng) < 200.0 for q in exempt):
                continue
            d, _i, _p = _closest_on(pts, m_lat, m_lng2, mlng)
            if d < 0.6 * r_std:
                return True
        return False

    def _complete_truncated_end(
        self, res: dict, req_end: tuple[float, float],
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        params: dict[str, Any] | None,
    ) -> None:
        """Version Moteur F de la complétion v5 : (1) extension A* REJETÉE si
        elle enfreint la discipline du chenal (→ suivi du balisage), (2)
        reliquat d'arrivée MESURÉ géométriquement (l'extension pouvait finir
        sur un nœud de grille à ~100 m du point demandé sans le signaler).
        Jamais bloquant : en cas d'échec, le résultat initial est rendu."""
        try:
            snap = res.get("end_snapped")
            wps = res.get("waypoints") or []
            if (not snap or len(wps) < 2
                    or not (_COMPLETE_MIN_M
                            <= float(snap.get("offset_m") or 0) <= 3000.0)):
                return
            anchor = (float(wps[-1]["lat"]), float(wps[-1]["lng"]))
            ext_w: list[dict] = []
            ext: dict = {}
            try:
                # Même moteur d'extension que la v5 : Moteur D (v4) en mode
                # MARÉE (plancher −2,5 m), contextvars E/F déjà armés.
                ext = SignalmarV4.compute_auto(
                    self,
                    anchor[0], anchor[1], req_end[0], req_end[1],
                    draft_m, depth_margin_m, lateral_margin_m,
                    tide_m=6.0, params=params,
                )
                ext_w = list(ext.get("waypoints") or [])
            except _v1.RouteError:
                ext_w = []
            # 13/08 (Moteur F) — LE BALISAGE PRIME : une extension qui laisse
            # une latérale fiable du mauvais côté ou frôle une balise (la
            # marée +6 m « ouvre » la vasière et l'A* coupe tout droit) est
            # remplacée par le suivi du chenal balisé.
            if len(ext_w) >= 2 and self._ext_violates(ext_w, req_end):
                ext_w = []
                ext = {}
            if len(ext_w) < 2:
                # 13/08 (Moteur F) — l'ANCRE elle-même peut être une arrivée
                # RELOGÉE en plein platier (nearest_reachable) : la route
                # principale y arrivait en frôlant N°4 à 0,7 m. On RECULE
                # l'ancre tant que le dernier tronçon enfreint la discipline
                # du chenal (≤ 5 crans), puis le suivi du balisage reprend
                # tout le trajet manquant.
                for _ in range(5):
                    if len(wps) < 3:
                        break
                    d_last = math.hypot(
                        (float(wps[-1]["lat"]) - req_end[0]) * M_PER_DEG_LAT,
                        (float(wps[-1]["lng"]) - req_end[1]) * m_per_deg_lng(req_end[0]))
                    d_prev = math.hypot(
                        (float(wps[-2]["lat"]) - req_end[0]) * M_PER_DEG_LAT,
                        (float(wps[-2]["lng"]) - req_end[1]) * m_per_deg_lng(req_end[0]))
                    overshoot = d_last > d_prev + 10.0  # on DÉPASSAIT l'arrivée
                    if not overshoot and not self._ext_violates(
                            [wps[-2], wps[-1]], req_end):
                        break
                    wps = wps[:-1]
                anchor = (float(wps[-1]["lat"]), float(wps[-1]["lng"]))
                ext_w = [{"lat": anchor[0], "lng": anchor[1]}]
            # 13/08 (Moteur F) — reliquat GÉOMÉTRIQUE (la v5 se fiait à
            # ``end_snapped`` de l'extension, absent quand l'A* s'arrête sur
            # un nœud de grille à ~100 m du point demandé).
            tail = (float(ext_w[-1]["lat"]), float(ext_w[-1]["lng"]))
            rest = math.hypot((tail[0] - req_end[0]) * M_PER_DEG_LAT,
                              (tail[1] - req_end[1]) * m_per_deg_lng(tail[0]))
            if rest > _DONE_M:
                chain = self._buoyed_channel_chain(tail, req_end)
                ext_w = ext_w + chain + [{"lat": req_end[0], "lng": req_end[1]}]
                rest = 0.0
            if len(ext_w) < 2:
                return
            # 14/08 (audit QA P0/FND-004) — JAMAIS DE TRONÇON SUR TERRE : le
            # point demandé peut être à terre (clic dans le port, quai…). Le
            # tronçon ajouté est sondé tous les ~25 m ; au premier
            # échantillon TERRE FERME (fond < −3,5 m au ZH ou hors donnée)
            # la route est TRONQUÉE au dernier point EN EAU et l'arrivée est
            # honnêtement signalée déplacée (fini le tracé qui grimpe à
            # −15 m sur le Crouesty avec un message rassurant).
            landed = False
            grid0 = _v1.get_grid()
            if grid0 is not None:
                kept = [ext_w[0]]
                for k in range(1, len(ext_w)):
                    a = kept[-1]
                    b = ext_w[k]
                    a_ll = (float(a["lat"]), float(a["lng"]))
                    b_ll = (float(b["lat"]), float(b["lng"]))
                    seg_m = math.hypot(
                        (b_ll[0] - a_ll[0]) * M_PER_DEG_LAT,
                        (b_ll[1] - a_ll[1]) * m_per_deg_lng(a_ll[0]))
                    n = max(2, int(seg_m / 25.0) + 1)
                    cut_t = None
                    for s in range(1, n + 1):
                        t = s / n
                        d = grid0.depth_at(
                            a_ll[0] + (b_ll[0] - a_ll[0]) * t,
                            a_ll[1] + (b_ll[1] - a_ll[1]) * t)
                        if d is None or d < _LAND_LIMIT_M:
                            cut_t = (s - 1) / n
                            break
                    if cut_t is None:
                        kept.append(b)
                        continue
                    if cut_t > 0.1:  # garde le dernier point encore EN EAU
                        kept.append({
                            "lat": round(a_ll[0] + (b_ll[0] - a_ll[0]) * cut_t, 6),
                            "lng": round(a_ll[1] + (b_ll[1] - a_ll[1]) * cut_t, 6),
                        })
                    landed = True
                    break
                if landed:
                    ext_w = kept
            n0 = len(wps) - 1
            merged = wps + [
                {"lat": float(w["lat"]), "lng": float(w["lng"])}
                for w in ext_w[1:]
            ]
            base_need = max(draft_m + depth_margin_m, -2.5)   # seuil au ZH
            comp = [i for i in _v1.shallow_legs(merged, base_need) if i >= n0]
            res["waypoints"] = merged
            if comp:
                res["compromised_legs"] = sorted(
                    set(res.get("compromised_legs") or []) | set(comp))
                res["risk"] = True
            # Balises du mauvais côté détectées sur l'extension : remontées.
            if ext.get("wrong_side_marks"):
                seen = {v.get("name") for v in (res.get("wrong_side_marks") or [])}
                res["wrong_side_marks"] = (res.get("wrong_side_marks") or []) + [
                    v for v in ext["wrong_side_marks"] if v.get("name") not in seen]
            # Distance + profil de profondeur recalculés sur le tracé complet.
            grid = _v1.get_grid()
            if grid is not None:
                fresh = _v1._result_for(grid, merged, base_need)
                for k in ("depth_profile", "min_depth_m", "distance_m"):
                    if k in fresh:
                        res[k] = fresh[k]
            res.pop("end_snapped", None)
            # 14/08 (Moteur F) — les avertissements de FRÔLEMENT du tracé
            # d'AVANT fusion/recul d'ancre deviennent obsolètes (le warning
            # « passe à ~1 m de N°4 » restait alors que le tronçon fautif
            # avait été remplacé) : purge + ré-audit du tracé fusionné.
            start_pt = (float(merged[0]["lat"]), float(merged[0]["lng"]))
            res["warnings"] = [
                w for w in (res.get("warnings") or [])
                if "arrivée déplacée" not in w
                and not w.startswith("⚠ La route passe à ~")
                and not w.startswith("Passage à ")
            ]
            res["warnings"].extend(
                _v1._mark_pass_audit(merged, (start_pt, req_end)))
            res["warnings"] = list(dict.fromkeys(res["warnings"]))
            # 13/08 (Moteur F) — avertissement « EN ROUGE » seulement s'il y
            # a réellement des tronçons compromis (le suivi du chenal balisé
            # trouve souvent la veine d'eau : pas de rouge, pas de peur).
            # 14/08 (audit QA P0) — arrivée à TERRE : ``end_snapped`` honnête
            # (offset mesuré) + avertissement franc, plus jamais de message
            # « suit le chenal balisé » sur un point injoignable en bateau.
            if landed:
                last = merged[-1]
                off_land = math.hypot(
                    (float(last["lat"]) - req_end[0]) * M_PER_DEG_LAT,
                    (float(last["lng"]) - req_end[1]) * m_per_deg_lng(req_end[0]))
                res["end_snapped"] = {
                    "offset_m": round(off_land, 1),
                    "reason": "arrivee_a_terre",
                }
                res["warnings"].insert(0, (
                    f"⚠ ARRIVÉE DEMANDÉE À TERRE / NON NAVIGABLE : la route "
                    f"s'arrête au dernier point en eau, à {off_land:.0f} m du "
                    f"point demandé. Déplacez l'arrivée sur l'eau pour aller "
                    f"plus loin."))
            elif comp:
                res["warnings"].insert(0, (
                    "⚠ FIN DE ROUTE EN ZONE PEU PROFONDE / DÉCOUVRANTE : le "
                    "dernier tronçon suit le chenal balisé jusqu'au point "
                    "demandé — les segments EN ROUGE exigent une hauteur de "
                    "marée suffisante."))
            else:
                res["warnings"].insert(0, (
                    "Le dernier tronçon suit le chenal balisé jusqu'au "
                    "point demandé."))
        except Exception:  # noqa: BLE001
            # 14/08 (audit QA FND-040) — une complétion en ÉCHEC n'est plus
            # silencieuse : le client sait que la route rendue est tronquée.
            res["completion_failed"] = True
            logger.exception("v6: complétion d'arrivée échouée, résultat rendu tel quel")


# ════════════════════════════════════════════════════════════════════════
# SECTION 3/3 — MOTEUR I (GO armateur 31/08/2026) : routes officielles
# écrêtées au TIRANT D'EAU RÉEL + doublons de balises neutralisés.
#
# 1. ÉCRÊTAGE AU TIRANT D'EAU : core/safe_routes.py (Moteur H, INCHANGÉ)
#    écrête les alignements (navigation_line) à 0,5 m au ZH — suffisant
#    pour « être en eau », pas pour FLOTTER. Cas mesuré (iter144/145) :
#    l'alignement OSM 711666732 traverse le banc du Turc (sondes réelles
#    1,4-2,3 m ≥ 0,5 m) et le Moteur H y cale la route telle quelle à
#    tirant 1,5 m. Ici le réseau est construit PAR BESOIN D'EAU
#    (tirant + marge − marée, plancher 0,5 m, cache par pas de 0,1 m) :
#    le pointillé est coupé là où le fond est insuffisant et le raccord
#    contourne par le calcul classique. Les tracés CHARTÉS
#    (recommended_track / two-way_route) restent NON écrêtés par la bathy
#    (la carte fait foi — artefacts lidar, iter145) : leurs hauts-fonds
#    restent signalés en tronçons rouges.
# 2. DOUBLONS CONTRADICTOIRES (« Les Errants », mesuré le 31/08) : deux
#    latérales bâbord HOMONYMES à 351 m — la tourelle BLANCHE
#    (id 1421434210, couleur qui CONTREDIT la catégorie) et la bouée
#    ROUGE (id 1421434206). En mode v6 leurs côtés requis divergent de
#    ~82° (blanche → EST, rouge → NORD) : l'écrêtage « mauvais côté »
#    des pointillés et l'audit final se contredisent. Règle Moteur I :
#    une latérale de couleur INCOHÉRENTE (bâbord non rouge / tribord non
#    verte) doublée par une homonyme de couleur CONFORME à ≤ 600 m ne
#    porte plus de règle de CÔTÉ (écrêtage des pointillés + audit final)
#    — son écart minimal (60 m, jamais traversée) est conservé.
#    safe_routes.py, seamarks.py et les moteurs A-H : STRICTEMENT
#    inchangés (tout est gated dans CE fichier).
# ════════════════════════════════════════════════════════════════════════
import json as _json

from core import safe_routes as _sr
from core.routing_engines.algos.signalmar_v4 import _required_side as _req_side

_LEG_SKIP_I_M = 60.0     # raccord plus court : pas de sous-calcul
# Plancher historique = safe_routes._CLIP_MIN_DEPTH (0,5 m au ZH). Valeur
# LITTÉRALE : au niveau module, safe_routes peut être partiellement
# initialisé (il importe signalmar_v4 → algos/__init__ → CE fichier).
_MIN_CLIP_M = 0.5
_DUP_NAME_M = 600.0                  # doublon homonyme : rayon d'appariement
_EXPECTED_COLOUR = {"port": "red", "starboard": "green"}

_suspect_ids_cache: Optional[frozenset] = None
_net_cache_i: dict = {}


def _suspect_duplicate_ids() -> frozenset:
    """Latérales « douteuses » : couleur incohérente avec la catégorie ET
    homonyme de couleur conforme à ≤ 600 m (cas « Les Errants »)."""
    global _suspect_ids_cache
    if _suspect_ids_cache is not None:
        return _suspect_ids_cache
    out: set = set()
    sm = get_seamarks()
    if sm is not None:
        groups: dict[tuple[str, str], list[dict]] = {}
        for m in sm.marks:
            name = (m.get("name") or "").strip()
            cat = m.get("category")
            if (m.get("kind") != "lateral" or not name
                    or cat not in _EXPECTED_COLOUR):
                continue
            groups.setdefault((name.lower(), cat), []).append(m)
        for (_name, cat), grp in groups.items():
            if len(grp) < 2:
                continue
            want = _EXPECTED_COLOUR[cat]
            good = [m for m in grp if want in (m.get("colour") or "").lower()]
            # Douteuse = couleur EXPLICITEMENT contradictoire (blanche sur
            # une bâbord…). Une couleur VIDE est un simple inconnu OSM
            # (perches génériques « perche babord ») : jamais neutralisée.
            bad = [m for m in grp
                   if (m.get("colour") or "").strip()
                   and want not in m["colour"].lower()]
            for b in bad:
                mlng = m_per_deg_lng(b["lat"])
                if any(math.hypot((b["lat"] - g["lat"]) * M_PER_DEG_LAT,
                                  (b["lng"] - g["lng"]) * mlng) <= _DUP_NAME_M
                       for g in good):
                    out.add(b["id"])
    _suspect_ids_cache = frozenset(out)
    return _suspect_ids_cache


def _wrong_side_i(sm, p) -> bool:
    """Copie de safe_routes._wrong_side (Moteur H, inchangé) qui IGNORE les
    doublons douteux : True si p est du mauvais côté d'une latérale FIABLE
    et non douteuse à ≤ 200 m."""
    if sm is None:
        return False
    skip = _suspect_duplicate_ids()
    mlng = m_per_deg_lng(p[0])
    for m in sm.marks:
        if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
            continue
        if m.get("id") in skip:
            continue
        d = math.hypot((m["lat"] - p[0]) * M_PER_DEG_LAT,
                       (m["lng"] - p[1]) * mlng)
        if d > _sr._SIDE_INFLUENCE_M:
            continue
        u = _req_side(sm, m)
        if u is None:
            continue
        ve = (p[1] - m["lng"]) * mlng
        vn = (p[0] - m["lat"]) * M_PER_DEG_LAT
        if ve * u[0] + vn * u[1] <= 0.0:
            return True
    return False


def _join_endpoints_i(net) -> None:
    """Jonctions synthétiques du réseau (mêmes règles que
    TrackNetwork._join_endpoints, Moteur H inchangé) mais contrôlées avec
    ``_wrong_side_i`` (doublons douteux ignorés)."""
    sm = get_seamarks()
    eps = net._endpoints
    for i, e in enumerate(eps):
        for f in eps[i + 1:]:
            if net.names[e] == net.names[f]:
                continue
            w = _sr._d_m(net.nodes[e], net.nodes[f])
            if w > _sr._JOIN_M:
                continue
            if sm is not None and any(
                    _wrong_side_i(sm, p)
                    for p in _sr._sample([net.nodes[e], net.nodes[f]])):
                continue
            net.adj[e].append((f, w))
            net.adj[f].append((e, w))


def _network_i(clip_m: float):
    """Réseau des routes officielles écrêté à ``clip_m`` (m au ZH) — le
    réseau dépend du besoin d'eau du bateau, cache par pas de 0,1 m."""
    key = round(max(clip_m, _MIN_CLIP_M), 1)
    net = _net_cache_i.get(key)
    if net is not None:
        return net
    if not _sr.SAFE_ROUTES_PATH.exists():
        return None
    data = _json.loads(_sr.SAFE_ROUTES_PATH.read_text())
    grid = _v1.get_grid()
    sm = get_seamarks()

    def _wet(p) -> bool:
        d = grid.depth_at(p[0], p[1])
        return d is not None and d >= key and not _wrong_side_i(sm, p)

    def _ok(p) -> bool:
        return not _wrong_side_i(sm, p)

    net = _sr.TrackNetwork()
    for f in data.get("features", []):
        kind = f.get("kind")
        if kind not in ("recommended_track", "navigation_line", "two-way_route"):
            continue
        pts = [(float(a), float(b)) for a, b in f.get("coords", [])]
        if len(pts) < 2 or f.get("closed"):
            continue
        name = f.get("name") or f"{kind} {f.get('id')}"
        if kind == "navigation_line":
            # Alignement : écrêté par la bathy AU BESOIN D'EAU du bateau.
            runs = _sr._split_runs(pts, _wet) if grid is not None else [pts]
        elif all(_ok(p) for p in _sr._sample(pts)):
            # Tracé charté entièrement conforme : renvoyé INTACT.
            runs = [pts]
        else:
            runs = _sr._split_runs(pts, _ok)
        for run in runs:
            net._add_polyline(run, name)
    _join_endpoints_i(net)
    if len(_net_cache_i) >= 8:
        _net_cache_i.clear()
    _net_cache_i[key] = net
    return net


def _plan_tracks_i(start, end, attach_m: float, bias: float,
                   clip_m: float) -> list[dict]:
    """Équivalent de safe_routes.plan_tracks (Moteur H, inchangé) sur le
    réseau écrêté au tirant d'eau — mêmes passes, mêmes scores."""
    net = _network_i(clip_m)
    if net is None or not net.nodes:
        return []
    comps = _sr._components(net)
    out: list[dict] = []
    used: set = set()

    def _emit(idxs, comp) -> None:
        used.update(comp)
        out.append({
            "pts": [net.nodes[i] for i in idxs],
            "names": list(dict.fromkeys(net.names[i] for i in idxs)),
        })

    cur = start
    for _pass in range(2):
        found = _sr._best_comp(net, comps, used, cur, end, attach_m, bias)
        if found is None:
            break
        idxs, comp = found
        _emit(idxs, comp)
        cur = net.nodes[idxs[-1]]
        if _sr._d_m(cur, end) <= _sr._MIN_PATH_M:
            break
    # Passe INVERSE : un système proche de l'ARRIVÉE, hors de portée du
    # raccordement côté départ (systèmes disjoints).
    if _sr._d_m(cur, end) > attach_m:
        found = _sr._best_comp(net, comps, used, end, cur, attach_m, bias)
        if found is not None:
            idxs, comp = found
            _emit(idxs[::-1], comp)
    return out


def _strip_suspect_wrong_sides(res: dict) -> None:
    """Retire de ``wrong_side_marks`` (et des warnings nominatifs) les
    entrées produites par un doublon douteux (« Les Errants » blanche) —
    l'homonyme fiable (bouée rouge) reste auditée. Jamais bloquant."""
    try:
        skip = _suspect_duplicate_ids()
        wsm = res.get("wrong_side_marks") or []
        wps = res.get("waypoints") or []
        sm = get_seamarks()
        if not skip or not wsm or len(wps) < 2 or sm is None:
            return
        pts = [(float(w["lat"]), float(w["lng"])) for w in wps]
        la = [q[0] for q in pts]
        mlng = m_per_deg_lng((min(la) + max(la)) / 2)   # même repère que l'audit
        drop: list[dict] = []
        for m in sm.marks:
            if m.get("id") not in skip:
                continue
            d, _i, _p = _closest_on(pts, m["lat"], m["lng"], mlng)
            name = m.get("name") or f"latérale {m['category']}"
            for v in wsm:
                if (v not in drop and v.get("name") == name
                        and v.get("category") == m.get("category")
                        and abs(float(v.get("dist_m") or -1e9) - d) <= 2.0):
                    drop.append(v)
                    break
        if not drop:
            return
        res["wrong_side_marks"] = [v for v in wsm if v not in drop]
        res["warnings"] = [
            w for w in (res.get("warnings") or [])
            if not (w.startswith("⚠ MAUVAIS CÔTÉ")
                    and any(v["name"] in w and f"~{v['dist_m']:.0f} m" in w
                            for v in drop))
        ]
    except Exception:  # noqa: BLE001
        logger.exception("i: filtrage des doublons wrong_side en échec")


__all__ = ["EngineI"]
