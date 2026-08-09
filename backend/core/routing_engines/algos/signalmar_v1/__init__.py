"""SignalMar — Algo « signalmar.v1 » (code historique isolé, 31/07/2026).

Ce module encapsule le calcul historique en tant qu'implémentation concrète
de ``BaseAlgo``. Le module interne ``core.py`` contient LE code d'origine
(1900 lignes, non modifié) — cette classe se contente de déléguer aux
fonctions ``compute_route``, ``manual_route``, ``nearest_navigable`` et
``shallow_legs`` du module.

Les futurs algos (``signalmar.v2``…) créeront leur propre sous-package et
leur propre classe ; celle-ci restera figée pour garantir que les moteurs
liés à ``signalmar.v1`` conservent un comportement identique à celui du
premier moteur SignalMar de production."""
from __future__ import annotations

from typing import Any

from core.routing_engines.base import BaseAlgo

# Import du code historique intact.
from . import core as _core

# Ré-exports (utiles pour le shim de compatibilité ``core.routing``).
RouteError = _core.RouteError
nearest_navigable = _core.nearest_navigable
shallow_legs = _core.shallow_legs


class SignalmarV1(BaseAlgo):
    """Algorithme historique SignalMar. NE PAS MODIFIER — tous les tests de
    non-régression (86 pytest) se réfèrent à son comportement. Pour tester
    une variante, créer un nouveau sous-package (``signalmar_v2``) et enre-
    gistrer la classe dans ``ALGO_REGISTRY``."""

    id = "signalmar.v1"
    version = "1.0.0"
    description = (
        "Moteur historique SignalMar (calcul ZH, IALA zone A, mode eau peu "
        "profonde). Base de comparaison pour toute variante future."
    )

    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        # v1 ignore ``params`` (algo à défauts figés). Les futurs algos
        # utiliseront les overrides.
        return _core.compute_route(
            start_lat, start_lng, end_lat, end_lng,
            draft_m, depth_margin_m, lateral_margin_m,
            tide_m=tide_m,
        )

    def compute_manual(
        self,
        waypoints: list[tuple[float, float]],
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        # v1 : manual_route ignore ``lateral_margin_m`` (pas d'A*). Le paramètre
        # est présent dans la signature de l'interface pour rester homogène
        # avec ``compute_auto`` et les futurs algos qui pourraient en tenir
        # compte (ex. audit de largeur autour d'une balise).
        return _core.manual_route(
            waypoints,
            draft_m, depth_margin_m,
            tide_m=tide_m,
        )


__all__ = ["SignalmarV1", "RouteError", "nearest_navigable", "shallow_legs"]
