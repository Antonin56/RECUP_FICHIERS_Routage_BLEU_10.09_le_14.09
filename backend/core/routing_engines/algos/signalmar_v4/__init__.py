"""SignalMar — Algo « signalmar.v4 » (MOTEUR D, base Moteur B, 10/08/2026).

Consigne armateur du 10/08 : « appliquer STRICTEMENT au moteur de routage la
notion de sens conventionnel — les moteurs n'ont jamais réussi à passer du
bon côté des bouées latérales lorsqu'il n'y a qu'UNE seule bouée (une rouge
ou une verte). Le Moteur B est PROTÉGÉ et FIGÉ, il sert de base de travail. »

v4 = v2 (Moteur B) À L'IDENTIQUE + le mode ``ISOLATED_SIDE_BATHY`` :

* **Côté de passage INVARIANT au sens de parcours.** « Verte à tribord en
  entrant » = « verte à bâbord en sortant » = le MÊME côté absolu de la
  bouée. Le vrai problème se réduit donc à : de quel côté GÉOGRAPHIQUE de la
  balise se trouve l'eau navigable ?
* **Latérale ISOLÉE → asymétrie bathymétrique** (``SeamarkIndex.
  navigable_side``) : une latérale marque une limite chenal/danger, l'eau
  profonde EST le chenal, le côté peu profond EST le danger signalé. Le
  demi-disque interdit du rasterize est posé du bon côté (au lieu du
  gradient « distance au large », faux de 90° en chenal étroit), et le
  balisage STRICT (extension à 200 m sur les cellules peu profondes du
  mauvais côté) s'applique aussi à ces isolées.
* **Hiérarchie des signaux** : couple rouge/verte (infaillible) → override
  manuel (``data/bathy/side_overrides.json``, validé terrain) → asymétrie
  bathymétrique nette → repli gradient (comportement B historique).
* **Audit nominatif** : le tracé final est contrôlé contre les latérales de
  direction FIABLE ; toute balise laissée du mauvais côté est remontée dans
  ``wrong_side_marks`` + un avertissement explicite (jamais bloquant).

Le mode est porté par un contextvar armé UNIQUEMENT le temps du calcul v4,
avec des caches séparés dans l'index : les Moteurs A, B et C sont
STRICTEMENT inchangés.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

from core.bathy import M_PER_DEG_LAT, m_per_deg_lng
from core.routing_engines.algos.signalmar_v2 import SignalmarV2
from core.routing_engines.algos.signalmar_v2.standoff import _closest_on
from core.seamarks import ISOLATED_SIDE_BATHY, get_seamarks

logger = logging.getLogger("signalmar.routing.v4")

Pt = tuple[float, float]

#: Une latérale à plus de cette distance du tracé n'impose pas son côté.
_INFLUENCE_M = 200.0
#: Balise proche du départ/de l'arrivée : exemptée (on quitte son mouillage).
_EXEMPT_M = 200.0


class SignalmarV4(SignalmarV2):
    id = "signalmar.v4"
    version = "4.0.0"
    description = (
        "Moteur D (base Moteur B du 10.08.26) : sens conventionnel appliqué "
        "STRICTEMENT aux latérales ISOLÉES — côté de passage déterminé par "
        "l'asymétrie bathymétrique (l'eau profonde = le chenal), hiérarchie "
        "couple rouge/verte → override terrain → bathymétrie → repli "
        "historique. Invariant au sens de parcours. Moteurs A/B/C inchangés."
    )

    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        tok = ISOLATED_SIDE_BATHY.set(True)
        try:
            res = super().compute_auto(
                start_lat, start_lng, end_lat, end_lng,
                draft_m, depth_margin_m, lateral_margin_m,
                tide_m=tide_m, params=params,
            )
            _audit_wrong_sides(res, (start_lat, start_lng), (end_lat, end_lng))
        finally:
            ISOLATED_SIDE_BATHY.reset(tok)
        return res

    def compute_manual(
        self,
        waypoints: list[tuple[float, float]],
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        # Route MANUELLE : jamais déplacée (intention explicite) — mais
        # l'audit de côté AVERTIT si un tracé laisse une balise du mauvais
        # côté (mêmes signaux fiables que l'auto).
        res = super().compute_manual(
            waypoints, draft_m, depth_margin_m, lateral_margin_m,
            tide_m=tide_m, params=params,
        )
        wps = res.get("waypoints") or []
        if len(wps) >= 2:
            tok = ISOLATED_SIDE_BATHY.set(True)
            try:
                _audit_wrong_sides(
                    res,
                    (float(wps[0]["lat"]), float(wps[0]["lng"])),
                    (float(wps[-1]["lat"]), float(wps[-1]["lng"])),
                )
            finally:
                ISOLATED_SIDE_BATHY.reset(tok)
        return res


# ── Audit du tracé final contre les latérales de direction FIABLE ─────────
def _required_side(sm, m: dict) -> Optional[tuple[float, float]]:
    """Vecteur unitaire (est, nord) du côté où le tracé doit passer, depuis
    la balise — UNIQUEMENT si la direction conventionnelle est fiable."""
    d = sm.mark_dir_confident(m)
    if d is None:
        return None
    de, dn = d
    # tribord(D) = (Dn, −De) ; bâbord(D) = (−Dn, De).
    return (dn, -de) if m["category"] == "port" else (-dn, de)


def _audit_wrong_sides(res: dict, start: Pt, end: Pt) -> None:
    """Ajoute ``wrong_side_marks`` + avertissements nominatifs au résultat.
    Jamais bloquant : en cas d'erreur, le résultat est rendu tel quel."""
    try:
        sm = get_seamarks()
        wps = res.get("waypoints") or []
        if sm is None or len(wps) < 2:
            return
        pts = [(float(w["lat"]), float(w["lng"])) for w in wps]
        la = [p[0] for p in pts]
        lo = [p[1] for p in pts]
        mlng = m_per_deg_lng((min(la) + max(la)) / 2)
        bad: list[dict] = []
        for m in sm.marks:
            if m.get("kind") != "lateral" or m.get("category") not in ("port", "starboard"):
                continue
            if not (min(la) - 0.01 <= m["lat"] <= max(la) + 0.01
                    and min(lo) - 0.01 <= m["lng"] <= max(lo) + 0.01):
                continue
            if any(math.hypot((m["lat"] - q[0]) * M_PER_DEG_LAT,
                              (m["lng"] - q[1]) * mlng) < _EXEMPT_M
                   for q in (start, end)):
                continue
            u = _required_side(sm, m)
            if u is None:
                continue
            influence = _INFLUENCE_M
            pair = sm._pair_of(m)
            if pair is not None:
                # 03/08 (leçon chenal d'Arradon) — une latérale APPAIRÉE
                # n'impose son côté que si le tracé emprunte la porte.
                gap = math.hypot((pair["lat"] - m["lat"]) * M_PER_DEG_LAT,
                                 (pair["lng"] - m["lng"]) * m_per_deg_lng(m["lat"]))
                influence = min(influence, max(0.8 * gap, 40.0))
            d, _i, p = _closest_on(pts, m["lat"], m["lng"], mlng)
            if d > influence:
                continue
            ve = (p[1] - m["lng"]) * mlng
            vn = (p[0] - m["lat"]) * M_PER_DEG_LAT
            if ve * u[0] + vn * u[1] > 0.0:
                continue  # bon côté
            bad.append({
                "name": m.get("name") or f"latérale {m['category']}",
                "kind": "lateral",
                "category": m["category"],
                "dist_m": round(d, 1),
                "side_required": ("à bâbord" if m["category"] == "port"
                                  else "à tribord"),
            })
        if not bad:
            return
        bad.sort(key=lambda v: v["dist_m"])
        res["wrong_side_marks"] = bad[:6]
        for v in bad[:3]:
            what = "rouge" if v["category"] == "port" else "verte"
            res.setdefault("warnings", []).insert(0, (
                f"⚠ MAUVAIS CÔTÉ DE BALISE : « {v['name']} » ({what}) doit "
                f"être laissée {v['side_required']} — passage à "
                f"~{v['dist_m']:.0f} m, vérifiez le balisage À VUE."
            ))
    except Exception:  # noqa: BLE001
        logger.exception("v4: audit de côté échoué, résultat rendu tel quel")


__all__ = ["SignalmarV4"]
