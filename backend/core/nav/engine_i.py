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
    version = "7.3.0"
    description = (
        "Moteur I (base Moteur F gelé au 27.08.26) : calcul du Moteur F + "
        "3 règles de balisage globales (armateur 01/09) — dédoublonnage "
        "intelligent des balises homonymes à ≤ 500 m (l'ambiguë est "
        "ignorée, seule la catégorisée fait foi), audit « mauvais côté » "
        "rectifié (secteur réellement interdit, faux couples corrigés), "
        "passage à ≥ 50 m de toute latérale (tracé repoussé si sûr), "
        "détours > 500 m redressés si la corde directe est sûre "
        "(secteur des cardinales contrôlé à 200 m, résultat déterministe). "
        "AUCUN suivi des routes officielles. Moteurs A-H inchangés."
    )

    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        """MOTEUR I (ORDRE ARMATEUR 31/08/2026) : le suivi/raccordement des
        routes officielles (pointillés) est SUPPRIMÉ INTÉGRALEMENT — mesuré
        sur Port-Navalo → SW Belle-Île, le planificateur hérité du Moteur H
        accrochait des chenaux dès qu'un point passait à ≤ 3 km de la ligne
        directe et les suivait au large (+9,3 km, zigzags entre les
        cailloux). Le Moteur I = calcul du MOTEUR F (identique au gelé,
        fond SHOM + respect du balisage + tirant d'eau), puis UNIQUEMENT
        les correctifs « Les Errants » (cf. section 3) : raccourci du
        détour fantôme adopté seulement s'il est strictement sûr, et
        filtrage des faux « mauvais côté » du doublon."""
        p2 = dict(params or {})
        p2["dir_coherence"] = False        # mode F pur, déterministe
        res = self._compute_base(
            start_lat, start_lng, end_lat, end_lng,
            draft_m, depth_margin_m, lateral_margin_m,
            tide_m=tide_m, params=p2)
        # Gardes armées autour des correctifs : les caches de direction
        # partagés (_dir_conf_v5/_dir_conf_v6) ne sont JAMAIS alimentés
        # depuis un état de contextvars différent de celui des moteurs
        # v6/H (pollution inter-moteurs mesurée sinon — audit H variable).
        tok5 = SIDE_ABSOLUTE.set(True)
        tok6 = SIDE_ABSOLUTE_V6.set(True)
        tokd = DIR_COHERENCE_V6.set(True)
        try:
            _bypass_suspect_detours(
                res, start=(start_lat, start_lng),
                requested_end=(end_lat, end_lng),
                draft_m=draft_m, depth_margin_m=depth_margin_m,
                lateral_margin_m=lateral_margin_m, tide_m=tide_m)
            _shortcut_large_detours(
                res, start=(start_lat, start_lng),
                requested_end=(end_lat, end_lng),
                draft_m=draft_m, depth_margin_m=depth_margin_m,
                lateral_margin_m=lateral_margin_m, tide_m=tide_m)
            _enforce_lateral_clearance(
                res, start=(start_lat, start_lng),
                requested_end=(end_lat, end_lng),
                draft_m=draft_m, depth_margin_m=depth_margin_m,
                lateral_margin_m=lateral_margin_m, tide_m=tide_m)
            _reaudit_dir_coherent(
                res, (start_lat, start_lng), (end_lat, end_lng))
            _strip_suspect_wrong_sides(res)
        finally:
            DIR_COHERENCE_V6.reset(tokd)
            SIDE_ABSOLUTE_V6.reset(tok6)
            SIDE_ABSOLUTE.reset(tok5)
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
# SECTION 3/3 — MOTEUR I : correctifs « LES ERRANTS » (doublon de balises).
#
# 31/08/2026 (ORDRE ARMATEUR) — le suivi des routes officielles
# (pointillés), son réseau écrêté, ses jonctions et son planificateur ont
# été SUPPRIMÉS INTÉGRALEMENT de ce moteur (mesuré : accrochage de chenaux
# à ≤ 3 km de la ligne directe → +9,3 km et zigzags sur Port-Navalo →
# SW Belle-Île). Il ne reste ici QUE le traitement du doublon mesuré le
# 31/08 : deux latérales bâbord HOMONYMES « Les Errants » à 351 m — la
# tourelle BLANCHE (id 1421434210, couleur qui CONTREDIT la catégorie) et
# la bouée ROUGE (id 1421434206), côtés requis v6 divergents de ~82°.
# Règle Moteur I :
#   · une latérale de couleur INCOHÉRENTE (bâbord non rouge / tribord non
#     verte) doublée par une homonyme de couleur CONFORME à ≤ 600 m est
#     « douteuse » : ses faux « mauvais côté » sont filtrés de l'audit, et
#     le détour fantôme qu'elle impose peut être raccourci — UNIQUEMENT si
#     le raccourci est strictement sûr (fond ≥ seuil couloir ±15 m +
#     portes, aucun frôlement — écart 60 m du doublon inclus —, aucun
#     mauvais côté d'une latérale fiable, mouillages/dangers respectés,
#     fond du profil JAMAIS dégradé) ; sinon le tracé F est rendu tel quel.
#   · couleur VIDE = simple inconnu OSM : jamais neutralisée (perches
#     génériques de Douarnenez = faux positifs écartés).
# safe_routes.py, seamarks.py et les moteurs A-H : STRICTEMENT inchangés.
# ════════════════════════════════════════════════════════════════════════

_DUP_NAME_M = 500.0        # doublon homonyme : rayon d'appariement (armateur 01/09)
_EXPECTED_COLOUR = {"port": "red", "starboard": "green"}

_suspect_ids_cache: Optional[frozenset] = None


def _suspect_duplicate_ids() -> frozenset:
    """DÉDOUBLONNAGE INTELLIGENT (armateur 01/09) : deux balises HOMONYMES
    à ≤ 500 m → celle dont la couleur/catégorie est AMBIGUË (blanche OU
    inconnue sur une latérale) est ignorée pour les règles de côté ; seule
    fait foi la balise officiellement catégorisée (latérale rouge/verte
    conforme, ou cardinale). Règle globale, toute zone."""
    global _suspect_ids_cache
    if _suspect_ids_cache is not None:
        return _suspect_ids_cache
    out: set = set()
    sm = get_seamarks()
    if sm is not None:
        groups: dict[str, list[dict]] = {}
        for m in sm.marks:
            name = (m.get("name") or "").strip()
            if not name or m.get("kind") not in ("lateral", "cardinal"):
                continue
            groups.setdefault(name.lower(), []).append(m)
        for grp in groups.values():
            if len(grp) < 2:
                continue

            def _conforme(m: dict) -> bool:
                if m.get("kind") == "cardinal":
                    return True
                want = _EXPECTED_COLOUR.get(m.get("category"))
                return bool(want) and want in (m.get("colour") or "").lower()

            good = [m for m in grp if _conforme(m)]
            bad = [m for m in grp if m.get("kind") == "lateral"
                   and m.get("category") in _EXPECTED_COLOUR
                   and not _conforme(m)]      # couleur vide OU contradictoire
            for b in bad:
                mlng = m_per_deg_lng(b["lat"])
                if any(math.hypot((b["lat"] - g["lat"]) * M_PER_DEG_LAT,
                                  (b["lng"] - g["lng"]) * mlng) <= _DUP_NAME_M
                       for g in good):
                    out.add(b["id"])
    _suspect_ids_cache = frozenset(out)
    return _suspect_ids_cache


_BYPASS_REACH_M = 450.0    # rayon du raccourci autour d'un doublon douteux
_BYPASS_MIN_GAIN_M = 40.0  # gain minimal : en deçà, pas un détour significatif


def _bypass_suspect_detours(
    res: dict, *, start: Pt, requested_end: Pt,
    draft_m: float, depth_margin_m: float, lateral_margin_m: float,
    tide_m: float,
) -> None:
    """31/08 (GO armateur) — DÉTOUR FANTÔME des doublons douteux SUPPRIMÉ.

    Le demi-disque rasterisé de la tourelle blanche « Les Errants »
    (seamarks.py, PARTAGÉ par les moteurs A-H, hors périmètre autorisé)
    impose au tracé un détour mesuré ~2× (1 690 m au lieu de ~900 m).
    Post-correction GÉOMÉTRIQUE du Moteur I, baseline Moteur F : le
    raccourci direct qui traverse la zone d'influence du doublon n'est
    adopté QUE s'il est STRICTEMENT sûr —
      · fond ≥ seuil sur couloir ±15 m + murs de porte (_Validator, seuil
        NORMAL, jamais le seuil marée) ;
      · AUCUN nouveau frôlement : tous les cercles d'écart respectés, Y
        COMPRIS celui du doublon lui-même (60 m, jamais traversé) ;
      · AUCUN mauvais côté d'une latérale fiable NON douteuse ;
      · mouillages et dangers isolés respectés (_seg_marks_ok) ;
      · jamais de régression du fond minimum du profil.
    Sinon le tracé F est rendu TEL QUEL. Règle GLOBALE (toute la façade) :
    s'applique à tout doublon détecté par ``_suspect_duplicate_ids``.
    Jamais bloquant."""
    try:
        skip = _suspect_duplicate_ids()
        if not skip:
            return
        grid = _v1.get_grid()
        sm = get_seamarks()
        wps = res.get("waypoints") or []
        if grid is None or sm is None or len(wps) < 3:
            return
        pts: list[Pt] = [(float(w["lat"]), float(w["lng"])) for w in wps]
        lat_s, lat_n, lng_w, lng_e = _bbox(pts)
        mlng = m_per_deg_lng((lat_s + lat_n) / 2)
        exempt = (start, requested_end)
        need = max(float(draft_m) + float(depth_margin_m) - float(tide_m), -2.5)
        strict = float(draft_m) + float(depth_margin_m) + 2.0
        gates_arr = None
        ga = [g for g in sm.gates(lat_s, lat_n, lng_w, lng_e)
              if not any(_d_m((g[0], g[1]), q[0], q[1], mlng) < 400.0
                         for q in exempt)]
        if ga:
            gates_arr = np.asarray(ga, dtype=np.float64)
        val = _Validator(grid, need, need, lateral_margin_m, gates_arr, strict)

        removed: list[str] = []
        for m in sm.marks:
            if m.get("id") not in skip:
                continue
            if not (lat_s - 0.01 <= m["lat"] <= lat_n + 0.01
                    and lng_w - 0.01 <= m["lng"] <= lng_e + 0.01):
                continue
            d0, _seg_i, _p0 = _closest_on(pts, m["lat"], m["lng"], mlng)
            if d0 > 1500.0:
                continue
            # Fenêtre de recherche : les points à ≤ 1,5 km du doublon (± 1).
            idx = [i for i, q in enumerate(pts)
                   if _d_m(q, m["lat"], m["lng"], mlng) < 1500.0]
            if not idx:
                continue
            lo = max(0, min(idx) - 1)
            hi = min(len(pts) - 1, max(idx) + 1)
            if hi - lo < 2:
                continue
            # Toutes les cordes i→j de la fenêtre (≤ 3 km), triées par GAIN
            # décroissant ; la première STRICTEMENT sûre gagne. La corde
            # doit passer dans la zone d'influence du doublon (le raccourci
            # ne s'attaque qu'aux détours attribuables au doublon).
            cands: list[tuple[float, int, int]] = []
            for i in range(lo, hi - 1):
                for j in range(i + 2, hi + 1):
                    a, b = pts[i], pts[j]
                    chord = _d_m(a, b[0], b[1], mlng)
                    if chord > 3000.0:
                        continue
                    dm, _ci, _cp = _closest_on([a, b], m["lat"], m["lng"], mlng)
                    if dm > _BYPASS_REACH_M:
                        continue
                    gain = _length_m(pts[i:j + 1], mlng) - chord
                    if gain >= _BYPASS_MIN_GAIN_M:
                        cands.append((gain, i, j))
            cands.sort(reverse=True)
            for gain, i, j in cands:
                a, b = pts[i], pts[j]
                if not val.seg_ok(a, b, allow_relaxed=False):
                    continue
                # Contrôles complets (mouillages + dangers isolés compris)
                # même quand le tracé de base a été calculé en mode F pur.
                tokd = DIR_COHERENCE_V6.set(True)
                try:
                    ok = _seg_marks_ok(sm, a, b, mlng, exempt, 200.0, ignore=m)
                finally:
                    DIR_COHERENCE_V6.reset(tokd)
                if not ok:
                    continue
                pts = pts[:i + 1] + pts[j:]
                removed.append(m.get("name") or f"latérale {m['category']}")
                break
        if not removed:
            return

        merged = [{"lat": round(q[0], 6), "lng": round(q[1], 6)} for q in pts]
        fresh = _v1._result_for(grid, merged, need)
        old_min = res.get("min_depth_m")
        new_min = fresh.get("min_depth_m")
        if (new_min is not None and old_min is not None
                and new_min < old_min - 0.05):
            return       # jamais de régression du profil de fond
        res["waypoints"] = fresh.get("waypoints") or merged
        for k in ("depth_profile", "min_depth_m", "distance_m"):
            if k in fresh:
                res[k] = fresh[k]
        base_need = max(float(draft_m) + float(depth_margin_m), -2.5)
        comp = list(_v1.shallow_legs(merged, base_need))
        if comp:
            res["compromised_legs"] = comp
            res["risk"] = True
        else:
            res.pop("compromised_legs", None)
            res.pop("risk", None)
        clearance = None
        cl = sm.clearance_points(lat_s, lat_n, lng_w, lng_e, need)
        if cl:
            clearance = np.asarray(cl, dtype=np.float64)
        res["corridor_m"] = _v1._corridors_for(grid, merged, need,
                                               lateral_margin_m, clearance)
        # Audits balises REJOUÉS sur le tracé final (warnings nominatifs
        # obsolètes purgés, wrong_side recalculé — même motif qu'ailleurs).
        res.pop("wrong_side_marks", None)
        res["warnings"] = [
            w for w in (res.get("warnings") or [])
            if not w.startswith("⚠ MAUVAIS CÔTÉ")
            and not w.startswith("⚠ La route passe à ~")
            and not w.startswith("Passage à ")
        ]
        res["warnings"].extend(_v1._mark_pass_audit(merged, exempt))
        for name in dict.fromkeys(removed):
            res["warnings"].append(
                f"Balisage en doublon « {name} » : détour fantôme supprimé "
                f"(tracé direct re-validé — fond, écart minimal 60 m et "
                f"balises voisines respectés).")
        res["warnings"] = list(dict.fromkeys(res["warnings"]))
        _audit_wrong_sides(res, exempt[0], exempt[1])
    except Exception:  # noqa: BLE001 — jamais bloquant, tracé F conservé
        logger.exception("i: bypass doublon en échec, tracé rendu tel quel")


# ── STABILITÉ (armateur 01/09, captures Golfe/Creizic Sud) ─────────────────
_DETOUR_GAIN_M = 500.0        # détour > 500 m → corde directe si sûre
_DETOUR_CHORD_MAX_M = 4000.0  # portée maxi d'une corde de redressement
_CARDINAL_SECTOR_M = 200.0    # secteur de contrôle autour d'une cardinale


def _cardinal_ok(sm, a: Pt, b: Pt, mlng: float) -> bool:
    """La corde a→b respecte le SECTEUR de toute cardinale à ≤ 200 m :
    passer au N d'une nord, au S d'une sud, à l'E d'une est, à l'O d'une
    ouest (règle carte, indépendante de la maille — supprime le « goulot
    mathématique » de l'A*)."""
    for m in sm.marks:
        if m.get("kind") != "cardinal":
            continue
        cat = (m.get("category") or "").lower()
        if cat not in ("north", "south", "east", "west"):
            continue
        d, _i, proj = _closest_on([a, b], m["lat"], m["lng"], mlng)
        if d > _CARDINAL_SECTOR_M:
            continue
        ve = (proj[1] - m["lng"]) * mlng
        vn = (proj[0] - m["lat"]) * M_PER_DEG_LAT
        ok = {"north": vn > 0.0, "south": vn < 0.0,
              "east": ve > 0.0, "west": ve < 0.0}[cat]
        if not ok:
            return False
    return True


def _shortcut_large_detours(
    res: dict, *, start: Pt, requested_end: Pt,
    draft_m: float, depth_margin_m: float, lateral_margin_m: float,
    tide_m: float,
) -> None:
    """PÉNALITÉ DE DÉTOUR + PERSISTANCE (armateur 01/09) : tout détour de
    plus de 500 m est remplacé par la corde directe UNIQUEMENT si elle est
    strictement sûre — fond ≥ seuil couloir ±15 m + portes, aucun
    frôlement (cercles d'écart respectés : on peut FRÔLER la zone de
    sécurité, jamais y entrer), aucun mauvais côté de latérale fiable,
    mouillages/dangers OK, SECTEUR des cardinales respecté (≥ 200 m de
    contrôle), fond du profil jamais dégradé. Post-traitement DÉTERMINISTE
    (indépendant de la maille de départ) : deux départs à 10 m d'écart
    convergent vers le même tracé redressé. Jamais bloquant."""
    try:
        sm = get_seamarks()
        grid = _v1.get_grid()
        wps = res.get("waypoints") or []
        if sm is None or grid is None or len(wps) < 3:
            return
        pts: list[Pt] = [(float(w["lat"]), float(w["lng"])) for w in wps]
        lat_s, lat_n, lng_w, lng_e = _bbox(pts)
        mlng = m_per_deg_lng((lat_s + lat_n) / 2)
        exempt = (start, requested_end)
        need = max(float(draft_m) + float(depth_margin_m) - float(tide_m), -2.5)
        strict = float(draft_m) + float(depth_margin_m) + 2.0
        gates_arr = None
        ga = [g for g in sm.gates(lat_s, lat_n, lng_w, lng_e)
              if not any(_d_m((g[0], g[1]), q[0], q[1], mlng) < 400.0
                         for q in exempt)]
        if ga:
            gates_arr = np.asarray(ga, dtype=np.float64)
        val = _Validator(grid, need, need, lateral_margin_m, gates_arr, strict)

        total_gain = 0.0
        for _pass in range(3):
            best = None            # (gain, i, j) — le PLUS GRAND détour d'abord
            n = len(pts)
            for i in range(n - 2):
                for j in range(n - 1, i + 1, -1):
                    a, b = pts[i], pts[j]
                    chord = _d_m(a, b[0], b[1], mlng)
                    if chord > _DETOUR_CHORD_MAX_M:
                        continue
                    gain = _length_m(pts[i:j + 1], mlng) - chord
                    if gain < _DETOUR_GAIN_M or (best and gain <= best[0]):
                        continue
                    if not val.seg_ok(a, b, allow_relaxed=False):
                        continue
                    if not _seg_marks_ok(sm, a, b, mlng, exempt, 200.0):
                        continue
                    if not _cardinal_ok(sm, a, b, mlng):
                        continue
                    best = (gain, i, j)
            if best is None:
                break
            gain, i, j = best
            pts = pts[:i + 1] + pts[j:]
            total_gain += gain
        if total_gain <= 0.0:
            return
        merged = [{"lat": round(q[0], 6), "lng": round(q[1], 6)} for q in pts]
        fresh = _v1._result_for(grid, merged, need)
        old_min, new_min = res.get("min_depth_m"), fresh.get("min_depth_m")
        if (new_min is not None and old_min is not None
                and new_min < old_min - 0.05):
            return       # jamais de régression du profil de fond
        res["waypoints"] = fresh.get("waypoints") or merged
        for k in ("depth_profile", "min_depth_m", "distance_m"):
            if k in fresh:
                res[k] = fresh[k]
        comp = list(_v1.shallow_legs(
            merged, max(float(draft_m) + float(depth_margin_m), -2.5)))
        if comp:
            res["compromised_legs"] = comp
            res["risk"] = True
        else:
            res.pop("compromised_legs", None)
            res.pop("risk", None)
        cl = sm.clearance_points(lat_s, lat_n, lng_w, lng_e, need)
        res["corridor_m"] = _v1._corridors_for(
            grid, merged, need, lateral_margin_m,
            np.asarray(cl, dtype=np.float64) if cl else None)
        res["warnings"] = [
            w for w in (res.get("warnings") or [])
            if not w.startswith("⚠ La route passe à ~")
            and not w.startswith("Passage à ")
        ]
        res["warnings"].extend(_v1._mark_pass_audit(merged, exempt))
        res["warnings"].append(
            f"Détour de ~{total_gain:.0f} m supprimé (tracé direct "
            f"re-validé — fond, écarts de sécurité, secteurs des "
            f"cardinales et balises respectés).")
        res["warnings"] = list(dict.fromkeys(res["warnings"]))
    except Exception:  # noqa: BLE001
        logger.exception("i: redressement des détours en échec — tracé rendu tel quel")


_MIN_LATERAL_CLEAR_M = 50.0   # armateur 01/09 : jamais « raser » une latérale


def _enforce_lateral_clearance(
    res: dict, *, start: Pt, requested_end: Pt,
    draft_m: float, depth_margin_m: float, lateral_margin_m: float,
    tide_m: float,
) -> None:
    """MARGE DE SÉCURITÉ (armateur 01/09) : passage à ≥ 50 m de TOUTE
    balise latérale (ou à l'écart recommandé de la marque s'il est plus
    grand — cas mesurés : Pengarne 35 m/53 m requis, No13 24 m/60 m). Le
    point fautif est repoussé radialement à la bonne distance, UNIQUEMENT
    si le tracé modifié reste strictement sûr (fond couloir ±15 m +
    portes, aucun frôlement/mauvais côté/mouillage/danger, fond du profil
    jamais dégradé) — sinon le tracé F est rendu tel quel (le warning de
    frôlement existant reste). Règle globale, toute zone. Jamais bloquant."""
    try:
        sm = get_seamarks()
        grid = _v1.get_grid()
        wps = res.get("waypoints") or []
        if sm is None or grid is None or len(wps) < 2:
            return
        pts: list[Pt] = [(float(w["lat"]), float(w["lng"])) for w in wps]
        lat_s, lat_n, lng_w, lng_e = _bbox(pts)
        mlng = m_per_deg_lng((lat_s + lat_n) / 2)
        exempt = (start, requested_end)
        need = max(float(draft_m) + float(depth_margin_m) - float(tide_m), -2.5)
        strict = float(draft_m) + float(depth_margin_m) + 2.0
        gates_arr = None
        ga = [g for g in sm.gates(lat_s, lat_n, lng_w, lng_e)
              if not any(_d_m((g[0], g[1]), q[0], q[1], mlng) < 400.0
                         for q in exempt)]
        if ga:
            gates_arr = np.asarray(ga, dtype=np.float64)
        val = _Validator(grid, need, need, lateral_margin_m, gates_arr, strict)

        changed = False
        for _pass in range(2):
            fixed = False
            for (d, _i, m, r_std, _n) in list(
                    graze_violations(sm, pts, exempt, mlng, 200.0)):
                if m.get("kind") != "lateral":
                    continue
                target = max(_MIN_LATERAL_CLEAR_M, float(r_std))
                dc, seg_i, proj = _closest_on(pts, m["lat"], m["lng"], mlng)
                if dc >= target - 0.5:
                    continue
                ue = (proj[1] - m["lng"]) * mlng
                un = (proj[0] - m["lat"]) * M_PER_DEG_LAT
                nrm = math.hypot(ue, un) or 1.0
                q: Pt = (m["lat"] + (un / nrm) * target / M_PER_DEG_LAT,
                         m["lng"] + (ue / nrm) * target / mlng)
                a, b = pts[seg_i], pts[seg_i + 1]
                if not (val.seg_ok(a, q, allow_relaxed=False)
                        and val.seg_ok(q, b, allow_relaxed=False)):
                    continue
                if not (_seg_marks_ok(sm, a, q, mlng, exempt, 200.0)
                        and _seg_marks_ok(sm, q, b, mlng, exempt, 200.0)):
                    continue
                pts = pts[:seg_i + 1] + [q] + pts[seg_i + 1:]
                changed = fixed = True
            if not fixed:
                break
        if not changed:
            return
        merged = [{"lat": round(q[0], 6), "lng": round(q[1], 6)} for q in pts]
        fresh = _v1._result_for(grid, merged, need)
        old_min, new_min = res.get("min_depth_m"), fresh.get("min_depth_m")
        if (new_min is not None and old_min is not None
                and new_min < old_min - 0.05):
            return       # jamais de régression du profil de fond
        res["waypoints"] = fresh.get("waypoints") or merged
        for k in ("depth_profile", "min_depth_m", "distance_m"):
            if k in fresh:
                res[k] = fresh[k]
        comp = list(_v1.shallow_legs(merged,
                                     max(float(draft_m) + float(depth_margin_m), -2.5)))
        if comp:
            res["compromised_legs"] = comp
            res["risk"] = True
        else:
            res.pop("compromised_legs", None)
            res.pop("risk", None)
        cl = sm.clearance_points(lat_s, lat_n, lng_w, lng_e, need)
        res["corridor_m"] = _v1._corridors_for(
            grid, merged, need, lateral_margin_m,
            np.asarray(cl, dtype=np.float64) if cl else None)
        # Warnings de frôlement recalculés sur le tracé corrigé.
        res["warnings"] = [
            w for w in (res.get("warnings") or [])
            if not w.startswith("⚠ La route passe à ~")
            and not w.startswith("Passage à ")
        ]
        res["warnings"].extend(_v1._mark_pass_audit(merged, exempt))
        res["warnings"] = list(dict.fromkeys(res["warnings"]))
    except Exception:  # noqa: BLE001
        logger.exception("i: écart latéral minimal en échec — tracé rendu tel quel")


def _reaudit_dir_coherent(res: dict, start: Pt, requested_end: Pt) -> None:
    """AUDIT DE PROXIMITÉ RECTIFIÉ (armateur 01/09) : « mauvais côté »
    déclenché UNIQUEMENT si le tracé coupe le secteur réellement interdit.
    L'audit hérité du F utilise la direction conventionnelle inférée par
    balise isolée — faussée par les FAUX COUPLES (mesuré : « La Petite
    Jument » flaguée à 61 m du BON côté). Ici l'audit est REJOUÉ sous
    cohérence de direction des chenaux (faux couples corrigés) — doit être
    appelé sous les contextvars armées de compute_auto. Jamais bloquant."""
    try:
        res.pop("wrong_side_marks", None)
        res["warnings"] = [w for w in (res.get("warnings") or [])
                           if not w.startswith("⚠ MAUVAIS CÔTÉ")]
        _audit_wrong_sides(res, start, requested_end)
    except Exception:  # noqa: BLE001
        logger.exception("i: ré-audit mauvais côté en échec")


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
