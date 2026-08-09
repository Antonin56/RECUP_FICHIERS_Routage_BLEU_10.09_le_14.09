"""SignalMar — Moteur C : CÔTÉ DE PASSAGE DES BALISES (03/08/2026).

RÈGLE 1 (consigne armateur, priorité absolue) : « les bouées rouges doivent
être laissées à bâbord (gauche), les vertes à tribord (droite) ».
Complétée le 03/08 (retour armateur, cardinale sud « Drenec ») : **les
CARDINALES doivent être passées du côté qu'elles désignent** (cardinale Sud →
on passe au SUD, le danger est au nord ; idem N/E/O).

Le tracé étant TOUJOURS calculé dans le sens conventionnel (mer → terre, cf.
``direction.py``), le cap local du tracé donne le sens conventionnel : aucune
estimation par gradient n'est nécessaire (c'était la cause racine du passage
du mauvais côté d'« Illur » par le Moteur B).

CONVENTION UNIQUE pour les deux familles de balises : on calcule ``u``, le
vecteur unitaire (est, nord) désignant le côté où le TRACÉ doit se trouver,
vu depuis la balise. Le tracé est du bon côté si ``(P − M) · u > 0``, où ``P``
est le point du tracé le plus proche et ``M`` la balise.

* latérale ROUGE (``port``) → ``u = tribord(D)`` (le tracé passe à droite de
  la bouée, donc la bouée reste à bâbord) ;
* latérale VERTE (``starboard``) → ``u = bâbord(D)`` ;
* cardinale Nord/Sud/Est/Ouest → ``u`` = direction géographique désignée.

POINT DE VIGILANCE (bug du 03/08) : ``_Ctx.seg_ok`` (hérité de la passe 3 du
moteur) ne contrôle QUE le fond et les portes de chenal — ni les cardinales,
ni le côté des autres latérales. Un contournement destiné à corriger une
balise pouvait donc en violer une autre. Chaque candidat est désormais
revalidé contre TOUTES les balises du voisinage : aucune violation NOUVELLE
n'est acceptée.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
from core.routing_engines.algos.signalmar_v2.standoff import (
    _closest_on, _d_m, _length_m,
)
from core.seamarks import get_seamarks

from .direction import heading_at, landward_dir

Pt = tuple[float, float]

#: Côté de passage OBLIGATOIRE d'une cardinale (est, nord).
_CARDINAL_SIDE: dict[str, tuple[float, float]] = {
    "north": (0.0, 1.0), "n": (0.0, 1.0),
    "south": (0.0, -1.0), "s": (0.0, -1.0),
    "east": (1.0, 0.0), "e": (1.0, 0.0),
    "west": (-1.0, 0.0), "w": (-1.0, 0.0),
}
_LATERAL_CATS = ("port", "starboard")


def conventional_dir_at(pts: list[Pt], seg_index: int, mlng: float,
                        mark: dict, dir_grid) -> tuple[float, float]:
    """Sens conventionnel LOCAL au point de passage : cap du tracé, retourné
    si le tracé y va vers le large. Fallback : cap du tracé tel quel."""
    he, hn = heading_at(pts, seg_index, mlng)
    g = landward_dir(mark["lat"], mark["lng"], dir_grid) if dir_grid is not None else None
    if g is not None and (he * g[0] + hn * g[1]) < 0.0:
        return (-he, -hn)
    return (he, hn)


def _required_side(pts: list[Pt], seg_index: int, mlng: float, mark: dict,
                   dir_grid) -> Optional[tuple[float, float]]:
    """Vecteur unitaire (est, nord) du côté où le TRACÉ doit passer."""
    if mark.get("kind") == "cardinal":
        return _CARDINAL_SIDE.get(str(mark.get("category") or "").lower())
    cat = mark.get("category")
    if cat not in _LATERAL_CATS:
        return None
    de, dn = conventional_dir_at(pts, seg_index, mlng, mark, dir_grid)
    # tribord(D) = (Dn, −De) ; bâbord(D) = (−Dn, De)
    return (dn, -de) if cat == "port" else (-dn, de)


def _influence_m(mark: dict, params: dict[str, Any]) -> float:
    if mark.get("kind") == "cardinal":
        return float(params["cardinal_influence_m"])
    influence = float(params["lateral_influence_m"])
    # 03/08 (fausse alerte « latérale starboard » au chenal d'Arradon) — une
    # latérale APPAIRÉE (porte de chenal) n'impose son côté que si le tracé
    # emprunte la porte. Au-delà de ~0,8 × l'écartement de la paire, la route
    # passe DEHORS (par le large ou par l'autre côté de l'île) et le côté de
    # passage n'a plus de sens : la paire du chenal d'Arradon est écartée de
    # 65 m, une route passant à 106 m n'y est pas.
    pair = mark.get("_pair")
    if pair:
        gap = math.hypot((pair["lat"] - mark["lat"]) * M_PER_DEG_LAT,
                         (pair["lng"] - mark["lng"]) * m_per_deg_lng(mark["lat"]))
        influence = min(influence, max(0.8 * gap, 40.0))
    return influence


def _exempt_m(mark: dict, params: dict[str, Any]) -> float:
    """Distance au départ/à l'arrivée DEMANDÉS en dessous de laquelle la balise
    n'impose plus son côté (on quitte / on rejoint son mouillage).

    03/08 (cardinale sud « Drenec ») — pour une CARDINALE, l'exemption couvre
    tout le rayon d'influence : si le point de départ est LUI-MÊME dans le
    secteur dangereux, aucun itinéraire ne peut respecter la règle, il faut
    d'abord en sortir. L'app avertit alors explicitement."""
    if mark.get("kind") == "cardinal":
        return max(float(params["side_exempt_m"]),
                   float(params["cardinal_influence_m"]))
    return float(params["side_exempt_m"])


def _target_m(mark: dict, params: dict[str, Any]) -> float:
    if mark.get("kind") == "cardinal":
        return float(params["cardinal_target_m"])
    return float(params["side_target_m"])


#: Cache de la portée du haut-fond signalé par une cardinale : (id, seuil) → m.
_REACH_CACHE: dict[tuple[Any, float], float] = {}


def _cardinal_reach_m(mark: dict, depth_gate, influence_m: float) -> Optional[float]:
    """Jusqu'où s'étend RÉELLEMENT le haut-fond signalé par la cardinale, le
    long de sa direction de danger (m). ``None`` si non mesurable.

    03/08 — le demi-disque de 300 m côté danger est une approximation
    grossière qui produisait deux erreurs OPPOSÉES :

    * chenal d'Arradon : au sud de la cardinale nord il y a 12 à 14 m de fond
      dès 100 m (le danger ne s'étend que sur ~40 m) → interdiction abusive
      qui empêchait de corriger « Truie d'Arradon » ;
    * cardinale sud « Drenec » : le fond reste à 8-9 m jusqu'à 150 m au nord
      puis tombe à 0,8 m vers 300 m → un test « eau peu profonde ENTRE la
      balise et le tracé » laissait passer un franchissement à 80 m.

    On mesure donc la distance de la PREMIÈRE eau peu profonde le long de la
    direction de danger (bande de ±25 m) : l'interdiction couvre cette
    distance + 80 m de sécurité, avec un minimum de 100 m. Autrement dit :
    « ne pas s'approcher à moins de 80 m du haut-fond que la balise signale ».
    Mesuré le 03/08 — Drenec : premier fond < 3,5 m à 200 m au nord →
    interdiction jusqu'à 280 m (un passage à 80, 150 ou 250 m est refusé) ;
    cardinale nord d'Arradon : roche à 30 m au sud → interdiction jusqu'à
    110 m (un passage à 150 ou 200 m reste autorisé)."""
    if depth_gate is None:
        return None
    grid, strict_depth = depth_gate
    if grid is None:
        return None
    side = _CARDINAL_SIDE.get(str(mark.get("category") or "").lower())
    if side is None:
        return None
    key = (mark.get("id") or (mark["lat"], mark["lng"]), float(strict_depth))
    cached = _REACH_CACHE.get(key)
    if cached is not None:
        return cached
    de, dn = -side[0], -side[1]          # direction du DANGER
    pe, pn = -dn, de                     # perpendiculaire
    mlng = m_per_deg_lng(mark["lat"])
    reach = -1.0
    r = 20.0
    while r <= influence_m and reach < 0.0:
        for off in (-25.0, 0.0, 25.0):
            lat = mark["lat"] + (dn * r + pn * off) / M_PER_DEG_LAT
            lng = mark["lng"] + (de * r + pe * off) / mlng
            d = grid.depth_at(lat, lng)
            if d is None or float(d) < strict_depth:
                reach = r
                break
        r += 20.0
    reach = max(reach, 0.0) if reach >= 0.0 else 0.0
    _REACH_CACHE[key] = reach
    return reach


def _cardinal_applies(mark: dict, d_track: float, depth_gate,
                      influence_m: float) -> bool:
    """La cardinale impose-t-elle son côté à un tracé passant à ``d_track`` ?"""
    reach = _cardinal_reach_m(mark, depth_gate, influence_m)
    if reach is None:
        return True                       # pas de bathy : prudence
    if reach <= 0.0:
        return False                      # aucun haut-fond dans le secteur
    return d_track <= max(100.0, reach + 80.0)


def relevant_marks(pts: list[Pt], pad: float = 0.01) -> list[dict]:
    """Latérales ROUGE/VERTE et cardinales de direction CONNUE du secteur."""
    sm = get_seamarks()
    if sm is None:
        return []
    la = [p[0] for p in pts]
    lo = [p[1] for p in pts]
    lat_s, lat_n = min(la) - pad, max(la) + pad
    lng_w, lng_e = min(lo) - pad, max(lo) + pad
    out: list[dict] = []
    for m in sm.marks:
        if not (lat_s <= m["lat"] <= lat_n and lng_w <= m["lng"] <= lng_e):
            continue
        kind = m.get("kind")
        if kind == "lateral" and m.get("category") in _LATERAL_CATS:
            out.append(m)
        elif kind == "cardinal" and str(m.get("category") or "").lower() in _CARDINAL_SIDE:
            out.append(m)
    return out


def _label(mark: dict) -> str:
    if mark.get("name"):
        return str(mark["name"])
    if mark.get("kind") == "cardinal":
        return f"cardinale {mark.get('category')}"
    return f"latérale {mark.get('category')}"


def _side_label(mark: dict) -> str:
    """Côté attendu, en clair, pour l'avertissement affiché à l'utilisateur."""
    if mark.get("kind") == "cardinal":
        return {"north": "au nord", "n": "au nord", "south": "au sud",
                "s": "au sud", "east": "à l'est", "e": "à l'est",
                "west": "à l'ouest", "w": "à l'ouest"}[
            str(mark.get("category")).lower()]
    return "à bâbord" if mark.get("category") == "port" else "à tribord"


def audit_sides(
    pts: list[Pt], *, mlng: float, params: dict[str, Any],
    exempt: tuple[Pt, ...] = (), marks: Optional[list[dict]] = None,
    dir_grid=None, depth_gate=None,
) -> list[dict]:
    """Balises que le tracé laisse du MAUVAIS côté, du plus critique au moins.

    ``[{name, kind, category, lat, lng, dist_m, seg_index, side_required}]``"""
    out: list[dict] = []
    for m in (marks if marks is not None else relevant_marks(pts)):
        exempt_m = _exempt_m(m, params)
        if any(_d_m((m["lat"], m["lng"]), q[0], q[1], mlng) < exempt_m for q in exempt):
            continue
        d, i, p = _closest_on(pts, m["lat"], m["lng"], mlng)
        if d > _influence_m(m, params):
            continue
        u = _required_side(pts, i, mlng, m, dir_grid)
        if u is None:
            continue
        ve = (p[1] - m["lng"]) * mlng
        vn = (p[0] - m["lat"]) * M_PER_DEG_LAT
        if ve * u[0] + vn * u[1] > 0.0:
            continue  # bon côté
        if m.get("kind") == "cardinal" and not _cardinal_applies(
                m, d, depth_gate, _influence_m(m, params)):
            continue  # haut-fond signalé trop local : le tracé est dégagé
        out.append({
            "name": _label(m),
            "kind": m.get("kind"),
            "category": m.get("category"),
            "lat": m["lat"], "lng": m["lng"],
            "dist_m": round(d, 1),
            "seg_index": i,
            "side_required": _side_label(m),
        })
    out.sort(key=lambda v: v["dist_m"])
    return out


def _violation_keys(viol: list[dict]) -> set[tuple[float, float]]:
    return {(round(v["lat"], 6), round(v["lng"], 6)) for v in viol}


def _arclens(pts: list[Pt], mlng: float) -> list[float]:
    s = [0.0]
    for a, b in zip(pts, pts[1:]):
        s.append(s[-1] + _d_m(a, b[0], b[1], mlng))
    return s


def _interp_at(pts: list[Pt], s: list[float], target: float) -> Pt:
    """Point du tracé à l'abscisse curviligne ``target`` (m)."""
    for k in range(len(pts) - 1):
        if s[k + 1] >= target:
            span = s[k + 1] - s[k]
            f = 0.0 if span < 1e-6 else (target - s[k]) / span
            return (pts[k][0] + (pts[k + 1][0] - pts[k][0]) * f,
                    pts[k][1] + (pts[k + 1][1] - pts[k][1]) * f)
    return pts[-1]


def _bridge(pts: list[Pt], mlng: float, s_center: float, half_len: float,
            q: Pt) -> Optional[tuple[list[Pt], int]]:
    """Remplace la portion de tracé de ``s_center ± half_len`` par un
    contournement passant par ``q``.

    03/08 — c'est LE correctif du cas « Illur » : insérer ``q`` entre deux
    waypoints de l'A* (espacés de plusieurs kilomètres en eau franche) créait
    un tronçon de 4,5 km entièrement dérouté, que le contrôle de couloir
    rejetait systématiquement. On ne dévie plus que quelques centaines de
    mètres autour de la balise. Retourne ``(tracé, index de q)``."""
    s = _arclens(pts, mlng)
    total = s[-1]
    if total < 40.0:
        return None
    s0 = max(1.0, s_center - half_len)
    s1 = min(total - 1.0, s_center + half_len)
    if s1 - s0 < 20.0:
        return None
    e_pt = _interp_at(pts, s, s0)
    x_pt = _interp_at(pts, s, s1)
    head = [p for k, p in enumerate(pts) if s[k] < s0]
    tail = [p for k, p in enumerate(pts) if s[k] > s1]
    if not head or not tail:
        return None
    return head + [e_pt, q, x_pt] + tail, len(head) + 1


def _push_to_side(
    pts: list[Pt], mark: dict, *, mlng: float, params: dict[str, Any],
    ctx, dir_grid=None, neighbours: Optional[list[dict]] = None,
    forbidden: Optional[set[tuple[float, float]]] = None,
    exempt: tuple[Pt, ...] = (), depth_gate=None,
) -> Optional[list[Pt]]:
    """Fait repasser le tracé du BON côté de ``mark`` SANS créer de nouvelle
    violation ailleurs. None si aucun contournement acceptable."""
    m_lat, m_lng = mark["lat"], mark["lng"]
    target_m = _target_m(mark, params)
    max_detour_m = float(params["side_max_detour_m"])
    d0, i0, p0 = _closest_on(pts, m_lat, m_lng, mlng)
    u = _required_side(pts, i0, mlng, mark, dir_grid)
    if u is None:
        return None
    ue, un = u
    len0 = _length_m(pts, mlng)
    s_all = _arclens(pts, mlng)
    s_center = s_all[i0] + _d_m(pts[i0], p0[0], p0[1], mlng)

    def _pt(vx: float, vy: float, r: float) -> Pt:
        return (m_lat + (vy * r) / M_PER_DEG_LAT, m_lng + (vx * r) / mlng)

    # Points de passage candidats, vus depuis la balise.
    offsets: list[tuple[float, float, float]] = []   # (est, nord, distance)
    for extra in (0.0, 30.0, 80.0, 160.0):
        for ang in (0.0, 25.0, -25.0):
            ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            offsets.append((ue * ca - un * sa, ue * sa + un * ca, target_m + extra))
    # 03/08 (chenal d'Arradon, « Truie d'Arradon ») — balise APPAIRÉE : le bon
    # point de passage est le MILIEU DE LA PORTE, pas un écart arbitraire du
    # bon côté (qui tombe souvent sur la vasière voisine).
    pair = mark.get("_pair")
    if pair:
        pe = (pair["lng"] - m_lng) * mlng
        pn = (pair["lat"] - m_lat) * M_PER_DEG_LAT
        gap = math.hypot(pe, pn)
        if gap > 20.0:
            for frac in (0.5, 0.4, 0.6, 0.35):
                offsets.insert(0, (pe / gap, pn / gap, gap * frac))

    scored: list[tuple[float, float, list[Pt], int]] = []
    for half_len in (float(params["side_bridge_m"]), 300.0, 600.0, 1000.0):
        for (ox, oy, r) in offsets:
            q = _pt(ox, oy, r)
            br = _bridge(pts, mlng, s_center, half_len, q)
            if br is None:
                continue
            cand, jq = br
            det = _length_m(cand, mlng) - len0
            if det > max_detour_m:
                continue
            if audit_sides(cand, mlng=mlng, params=params, marks=[mark],
                           dir_grid=dir_grid, depth_gate=depth_gate):
                continue  # toujours du mauvais côté de la balise visée
            # Aucune violation NOUVELLE ailleurs (cardinales incluses) :
            # corriger « Illur » ne doit pas casser « Drenec ».
            if neighbours:
                after = _violation_keys(audit_sides(
                    cand, mlng=mlng, params=params, marks=neighbours,
                    exempt=exempt, dir_grid=dir_grid, depth_gate=depth_gate))
                if after - (forbidden or set()):
                    continue
            d2, _, _ = _closest_on(cand, m_lat, m_lng, mlng)
            if d2 < min(target_m, max(d0, 15.0)) - 2.0:
                continue
            scored.append((-d2, det, cand, jq))
    if not scored:
        return None
    # Écart le plus large d'abord ; à écart égal, le détour le plus court.
    scored.sort(key=lambda t: (t[0], t[1]))
    for (_neg_d, _det, cand, jq) in scored[:12]:
        if not ctx.point_ok(cand[jq]):
            continue
        lo = max(0, jq - 2)
        hi = min(len(cand) - 1, jq + 3)
        if all(ctx.seg_ok(cand[k], cand[k + 1]) for k in range(lo, hi)):
            return cand
    return None


def enforce_sides(
    pts: list[Pt], *, mlng: float, ctx, params: dict[str, Any],
    exempt: tuple[Pt, ...] = (), dir_grid=None, depth_gate=None,
) -> tuple[list[Pt], list[str], list[dict]]:
    """Applique la RÈGLE 1 au tracé. Retourne
    ``(tracé, balises corrigées, violations restantes)``.

    Ne lève jamais : ce qui ne peut pas être corrigé est REMONTÉ (le tracé est
    conservé, l'app affiche un avertissement « mauvais côté de balise »)."""
    budget = int(params["side_max_marks"])
    marks = relevant_marks(pts)
    fixed: list[str] = []
    for _round in range(3):
        viol = audit_sides(pts, mlng=mlng, params=params, exempt=exempt,
                           marks=marks, dir_grid=dir_grid, depth_gate=depth_gate)
        if not viol or budget <= 0:
            break
        # Les violations DÉJÀ présentes sont tolérées comme état de départ :
        # on interdit seulement d'en créer de nouvelles.
        forbidden = _violation_keys(viol)
        progressed = False
        for v in viol[:budget]:
            mark = next((m for m in marks
                         if round(m["lat"], 6) == round(v["lat"], 6)
                         and round(m["lng"], 6) == round(v["lng"], 6)), None)
            if mark is None:
                continue
            cand = _push_to_side(
                pts, mark, mlng=mlng, params=params, ctx=ctx,
                dir_grid=dir_grid, neighbours=marks, forbidden=forbidden,
                exempt=exempt, depth_gate=depth_gate,
            )
            if cand is None:
                continue
            pts = cand
            budget -= 1
            progressed = True
            if v["name"] not in fixed:
                fixed.append(v["name"])
            forbidden = _violation_keys(audit_sides(
                pts, mlng=mlng, params=params, exempt=exempt, marks=marks,
                dir_grid=dir_grid, depth_gate=depth_gate))
        if not progressed:
            break
    remaining = audit_sides(pts, mlng=mlng, params=params, exempt=exempt,
                            marks=marks, dir_grid=dir_grid, depth_gate=depth_gate)
    return pts, fixed, remaining


__all__ = ["audit_sides", "enforce_sides", "conventional_dir_at", "relevant_marks"]
