"""SignalMar — Algo « signalmar.h » (MOTEUR H, base Moteur F, 26/08/2026).

GO armateur du 26/08 : « Moteur H qui suit les routes officielles et corrige
les faux couples ». Moteurs A-G STRICTEMENT inchangés (mêmes gardes
contextvars que les itérations précédentes).

1. **ROUTES OFFICIELLES PRIORITAIRES** : si une ou plusieurs routes sûres
   (pointillés des cartes : recommended_track / alignements écrêtés) sont
   détectées près du trajet, la route est CALÉE dessus — la plus courte qui
   rapproche de la destination ; si elle ne va pas jusqu'au bout, on la suit
   au plus proche puis le calcul classique (Moteur F) fait le reste. Aucune
   route détectée → calcul Moteur F intégral (repli).
2. **FAUX COUPLES corrigés** : règles de cohérence de direction
   (``dir_coherence`` : la bathy prime sur un couple contredit par l'eau
   profonde, consensus des voisines fiables) TOUJOURS actives — c'est ce qui
   corrige « La Petite Jument » et « N° 4 » à Lorient.
3. **PRIORITÉ AU BALISAGE DE CHENAL** (rayon paramétrable, défaut 1 km,
   ``params.chenal_radius_m``, ajustable par API sans UI) : en présence d'une
   latérale fiable dans ce rayon, une CARDINALE ne détourne plus la route
   (elle reste un obstacle : écart minimal audité, jamais traversée).

Paramètres du moteur (overrides via ``engines.params``) :
- ``track_attach_m``  (défaut 3000) : rayon de raccordement au réseau ;
- ``chenal_radius_m`` (défaut 1000) : rayon de la règle latérales/cardinales.
"""
from __future__ import annotations

import logging
from typing import Any

from core import safe_routes
from core.routing_engines.algos.signalmar_v1 import core as _v1
from core.routing_engines.algos.signalmar_v4 import _audit_wrong_sides
from core.routing_engines.algos.signalmar_v6 import SignalmarV6
from core.seamarks import (
    DIR_COHERENCE_V6, LATERAL_AUTHORITY_M, SIDE_ABSOLUTE, SIDE_ABSOLUTE_V6,
)

logger = logging.getLogger("signalmar.routing.h")

_LEG_SKIP_M = 60.0          # raccord plus court : pas de sous-calcul


class SignalmarH(SignalmarV6):
    id = "signalmar.h"
    version = "1.0.0"
    description = (
        "Moteur H (base Moteur F) : routes OFFICIELLES prioritaires (la "
        "route est calée sur les pointillés des cartes quand ils existent, "
        "repli Moteur F sinon), faux couples corrigés (la bathy et le "
        "consensus des voisines priment), latérales prioritaires sur les "
        "cardinales dans un rayon paramétrable (défaut 1 km). "
        "Moteurs A-G inchangés."
    )

    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        p = dict(params or {})
        p.setdefault("dir_coherence", True)          # faux couples corrigés
        radius = float(p.get("chenal_radius_m", 1000.0))
        attach = float(p.get("track_attach_m", 3000.0))
        tok = LATERAL_AUTHORITY_M.set(max(radius, 0.0))
        # Contextvars armés sur TOUTE la durée (audit final du tracé assemblé
        # compris) : directions corrigées des faux couples, caches v5/v6.
        tok5 = SIDE_ABSOLUTE.set(True)
        tok6 = SIDE_ABSOLUTE_V6.set(True)
        tokd = DIR_COHERENCE_V6.set(True)
        try:
            plan: list[dict] = []
            try:
                plan = safe_routes.plan_tracks(
                    (start_lat, start_lng), (end_lat, end_lng), attach,
                    bias=float(p.get("track_bias", 1.4)))
            except Exception:                        # noqa: BLE001
                logger.exception("h: plan routes officielles en échec — repli F")
            if not plan:
                return super().compute_auto(
                    start_lat, start_lng, end_lat, end_lng,
                    draft_m, depth_margin_m, lateral_margin_m,
                    tide_m=tide_m, params=p)
            try:
                return self._compute_with_tracks(
                    plan, start_lat, start_lng, end_lat, end_lng,
                    draft_m, depth_margin_m, lateral_margin_m, tide_m, p)
            except _v1.RouteError:
                raise
            except Exception:                        # noqa: BLE001
                logger.exception("h: assemblage routes officielles en échec — repli F")
                return super().compute_auto(
                    start_lat, start_lng, end_lat, end_lng,
                    draft_m, depth_margin_m, lateral_margin_m,
                    tide_m=tide_m, params=p)
        finally:
            DIR_COHERENCE_V6.reset(tokd)
            SIDE_ABSOLUTE_V6.reset(tok6)
            SIDE_ABSOLUTE.reset(tok5)
            LATERAL_AUTHORITY_M.reset(tok)

    # ── Assemblage : raccords Moteur F + tronçons « route officielle » ────
    def _compute_with_tracks(
        self, plan: list[dict],
        start_lat: float, start_lng: float, end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float, p: dict[str, Any],
    ) -> dict:
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
            if safe_routes._d_m(a, b) < _LEG_SKIP_M:
                return None
            res = super(SignalmarH, self).compute_auto(
                a[0], a[1], b[0], b[1],
                draft_m, depth_margin_m, lateral_margin_m,
                tide_m=tide_m, params=p)
            return res

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
        if leg:
            n0 = len(merged)
            _extend(leg.get("waypoints") or [])
            risk |= bool(leg.get("risk"))
            compromised += [n0 + i for i in (leg.get("compromised_legs") or [])]
            if leg.get("end_snapped"):
                end_snapped = leg["end_snapped"]
            else:
                end_snapped = None
            for w in (leg.get("warnings") or []):
                if w.startswith("⚠ ARRIVÉE") or w.startswith("⚠ FIN DE ROUTE"):
                    warnings.append(w)
        else:
            end_snapped = None
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
            f"(pointillés de la carte)."] + warnings
        res["warnings"].extend(_v1._mark_pass_audit(
            merged, ((start_lat, start_lng), (end_lat, end_lng))))
        res["warnings"] = list(dict.fromkeys(res["warnings"]))
        _audit_wrong_sides(res, (start_lat, start_lng), (end_lat, end_lng))
        return res


__all__ = ["SignalmarH"]
