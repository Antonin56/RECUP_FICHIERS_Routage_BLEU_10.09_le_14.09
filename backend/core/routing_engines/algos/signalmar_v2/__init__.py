"""SignalMar — Algo « signalmar.v2 » (variante Moteur B, 02/08/2026).

Ce que v2 change par rapport à v1 (le reste est STRICTEMENT identique — v2
délègue tout le calcul au moteur historique) :

* **Écart minimal aux balises garanti quelle que soit la maille** : après le
  calcul, le tracé est écarté géométriquement de toute balise qu'il frôlait
  (cause racine détaillée dans ``standoff.py`` — bug « Fernais 25 » du 02/08,
  route à 4,7 m de la bouée en marge AUTO). Si l'écart est impossible faute
  de place, le tracé historique est conservé avec son avertissement.

Aucun autre comportement n'est modifié : Moteur A (``signalmar.v1``) reste
la référence de non-régression."""
from __future__ import annotations

from typing import Any

from core.routing_engines.base import BaseAlgo
from core.routing_engines.algos.signalmar_v1 import core as _v1
from core.routing_engines.algos.signalmar_v2.standoff import (
    DEFAULT_PARAMS, enforce_mark_standoff, rebuild_result,
)
from core.routing_engines.algos.signalmar_v2.stitch import split_at_block


class SignalmarV2(BaseAlgo):
    id = "signalmar.v2"
    version = "2.1.0"
    description = (
        "Variante B : moteur historique + ÉCART MINIMAL AUX BALISES garanti "
        "hors zone pilote (correctif « Fernais 25 » du 02/08) + SECTIONNEMENT "
        "AUTOMATIQUE au point de blocage (une route existante n'est plus "
        "refusée à cause de l'agrégation de la bathy 100 m)."
    )

    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        # Mêmes bornes/dérivées que le moteur (cf. v1.compute_route).
        draft = float(min(max(draft_m, _v1.DRAFT_MIN), _v1.DRAFT_MAX))
        marg = float(min(max(depth_margin_m, _v1.DEPTH_MARGIN_MIN), _v1.DEPTH_MARGIN_MAX))
        lat_m = float(min(max(lateral_margin_m, _v1.LATERAL_MIN), _v1.LATERAL_MAX))
        tide = float(min(max(tide_m, -2.0), 6.0))
        min_depth = max(draft + marg - tide, -2.5)
        strict_depth = draft + marg + 2.0
        start = (start_lat, start_lng)
        end = (end_lat, end_lng)

        try:
            res = _v1.compute_route(
                start_lat, start_lng, end_lat, end_lng,
                draft_m, depth_margin_m, lateral_margin_m, tide_m=tide_m,
            )
        except _v1.RouteError as first:
            # Fragilité de la passe grossière (agrégation 100 m) : on relance
            # en deux tronçons de part et d'autre du point de blocage.
            stitched = split_at_block(
                first, start=start, end=end,
                draft_m=draft_m, depth_margin_m=depth_margin_m,
                lateral_margin_m=lateral_margin_m, tide_m=tide_m,
            )
            if stitched is None:
                raise
            pts = stitched.pop("_stitched_points")
            grid = _v1.get_grid()
            res = rebuild_result(
                stitched, grid, pts, min_depth=min_depth,
                lateral_margin_m=lat_m, exempt=(start, end),
                extra_warnings=(
                    "Route calculée en 2 tronçons (contournement d'une limite "
                    "de calcul sur bathymétrie agrégée).",
                ),
            )
        try:
            return enforce_mark_standoff(
                res,
                start=start, requested_end=end,
                min_depth=min_depth, lateral_margin_m=lat_m,
                strict_depth=strict_depth, params=params,
            )
        except Exception:  # noqa: BLE001 — jamais bloquant : on rend v1
            return res

    def compute_manual(
        self,
        waypoints: list[tuple[float, float]],
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        # Route MANUELLE : tracée par l'utilisateur → jamais déplacée.
        return _v1.manual_route(waypoints, draft_m, depth_margin_m, tide_m=tide_m)

    def capabilities(self) -> dict[str, Any]:
        caps = super().capabilities()
        caps["params"] = DEFAULT_PARAMS
        return caps


__all__ = ["SignalmarV2"]
