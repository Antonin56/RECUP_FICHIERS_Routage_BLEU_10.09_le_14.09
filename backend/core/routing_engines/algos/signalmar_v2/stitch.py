"""SignalMar — SECTIONNEMENT AUTOMATIQUE au point de blocage (02/08/2026).

Variante **Moteur B** (algo ``signalmar.v2``).

FRAGILITÉ CORRIGÉE (mesurée) : hors zone pilote, la passe grossière travaille
sur une bathy agrégée (maille 100 m, agrégation prudente = fond mini du bloc).
Le découpage de cette agrégation dépend de la **fenêtre**, donc des points de
départ/arrivée demandés : déplacer l'arrivée de 60 m suffisait à refermer un
passage étroit et à conclure « Passage impossible » alors que la route existe.

Cas de référence (Loire → Golfe, tirant 1,0 m / marge 0,5 m) :
  * arrivée 47.5614 / -2.87473 → ÉCHEC en 3,5 s, blocage annoncé sur un
    haut-fond à -2,52 m (47.2319 / -2.2983) ;
  * arrivée 47.5614 / -2.87550 (77 m plus à l'ouest) → route trouvée, 84,4 km.

CORRECTIF (sans toucher au Moteur A) : quand le moteur historique renonce en
donnant son **point de blocage**, on relance le calcul en DEUX TRONÇONS de part
et d'autre de ce point. Chaque tronçon a une fenêtre plus petite, donc une
bathy moins agrégée, et le passage étroit reste ouvert. Mesure sur le cas de
référence : 84,58 km en 1,4 s (+180 m seulement par rapport au tracé « chanceux »).
Si un tronçon échoue à son tour, l'erreur d'origine est renvoyée telle quelle.
"""
from __future__ import annotations

import math
from typing import Optional

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
from core.routing_engines.algos.signalmar_v1 import core as v1

#: Un sectionnement n'a de sens que si le blocage est loin des extrémités.
MIN_LEG_M = 400.0
#: Rallonge maximale acceptée par rapport au tronçon direct théorique.
MAX_TOTAL_FACTOR = 3.0


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((b[0] - a[0]) * M_PER_DEG_LAT,
                      (b[1] - a[1]) * m_per_deg_lng((a[0] + b[0]) / 2))


def split_at_block(
    err: v1.RouteError, *,
    start: tuple[float, float], end: tuple[float, float],
    draft_m: float, depth_margin_m: float, lateral_margin_m: float,
    tide_m: float, depth: Optional[int] = 0,
) -> Optional[dict]:
    """Relance le calcul en deux tronçons autour du point de blocage.

    Retourne le résultat recousu, ou ``None`` si le sectionnement n'est pas
    applicable / n'aboutit pas (l'appelant renvoie alors l'erreur d'origine)."""
    payload = err.payload or {}
    blk = payload.get("blocked_at")
    if not isinstance(blk, dict):
        return None
    try:
        via = (float(blk["lat"]), float(blk["lng"]))
    except (KeyError, TypeError, ValueError):
        return None
    if _dist_m(start, via) < MIN_LEG_M or _dist_m(via, end) < MIN_LEG_M:
        return None

    def _leg(a: tuple[float, float], b: tuple[float, float]) -> dict:
        return v1.compute_route(
            a[0], a[1], b[0], b[1],
            draft_m, depth_margin_m, lateral_margin_m, tide_m=tide_m,
        )

    try:
        leg0 = _leg(start, via)
    except v1.RouteError:
        return None
    w0 = leg0.get("waypoints") or []
    if len(w0) < 2:
        return None
    # Le tronçon 2 part du point RÉELLEMENT atteint (continuité garantie).
    junction = (float(w0[-1]["lat"]), float(w0[-1]["lng"]))
    try:
        leg1 = _leg(junction, end)
    except v1.RouteError as second:
        # Un seul re-découpage supplémentaire (bornage du temps de calcul).
        if depth and depth > 0:
            return None
        deeper = split_at_block(
            second, start=junction, end=end,
            draft_m=draft_m, depth_margin_m=depth_margin_m,
            lateral_margin_m=lateral_margin_m, tide_m=tide_m, depth=1,
        )
        if deeper is None:
            return None
        leg1 = deeper
    w1 = leg1.get("waypoints") or []
    if len(w1) < 2:
        return None

    direct = _dist_m(start, end)
    total = float(leg0["distance_m"]) + float(leg1["distance_m"])
    if direct > 0 and total > direct * MAX_TOTAL_FACTOR:
        return None  # détour déraisonnable : mieux vaut l'erreur franche

    pts = [(float(w["lat"]), float(w["lng"])) for w in w0]
    for w in w1[1:]:
        pts.append((float(w["lat"]), float(w["lng"])))

    # Le tronçon 2 porte l'état de l'arrivée (relogement éventuel).
    out = dict(leg1)
    out["mode"] = leg0.get("mode", out.get("mode"))
    out["warnings"] = list(dict.fromkeys(
        list(leg0.get("warnings") or []) + list(leg1.get("warnings") or [])
    ))
    out["split_via"] = {"lat": round(via[0], 6), "lng": round(via[1], 6)}
    out["_stitched_points"] = pts
    return out
