"""SignalMar — Interface commune aux ALGORITHMES de routage (31/07/2026).

Distinction fondamentale entre :

* **Algorithme** (« algo ») : code Python versionné (ex. ``signalmar.v1``).
  Un algo est une implémentation concrète de la logique de calcul, avec
  ses paramètres internes par défaut. Les algos sont enregistrés dans
  ``core.routing_engines.algos.ALGO_REGISTRY``. Changer un algo requiert
  un déploiement de code.
* **Moteur** (« engine ») : profil nommé, persistant (MongoDB), qui lie un
  algo à d'éventuels overrides de paramètres + un nom d'affichage. Plusieurs
  moteurs peuvent partager le même algo. L'utilisateur peut dupliquer,
  renommer et basculer entre moteurs depuis son profil sans aucun changement
  de code.

Cette dualité permet à l'armateur de tester des variantes de routage :
* Réglage fin (paramètres) → clone d'un moteur + override des ``params``.
* Refonte algorithmique → nouvel algo (ex. ``signalmar.v2``) créé en code,
  auquel on rebinde le moteur cible ; les autres moteurs continuent sur
  ``signalmar.v1`` sans impact.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAlgo(ABC):
    """Contrat minimal pour tous les algorithmes de routage SignalMar.

    L'algo reçoit toujours ses paramètres dans ``params`` — un simple ``dict``
    d'overrides à fusionner avec ses défauts internes. Les overrides peuvent
    être vides (``{}``) : dans ce cas l'algo se comporte avec ses défauts
    historiques (rétrocompatibilité stricte)."""

    #: Identifiant stable (``signalmar.v1``, ``signalmar.v2``…). Sert de clé
    #: dans ``ALGO_REGISTRY`` et pour le binding depuis les documents Moteur.
    id: str = "base"
    #: Version affichée (utile pour tracer quelle logique a généré une route).
    version: str = "0.0.0"
    #: Description en clair (surface UI et endpoint ``/routing/engines``).
    description: str = ""

    @abstractmethod
    def compute_auto(
        self,
        start_lat: float, start_lng: float,
        end_lat: float, end_lng: float,
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        """Calcul de route automatique (A* + règles). Doit retourner un dict
        au shape historique : ``{waypoints, distance_m, min_depth_m, warnings,
        risk?, shallow_route?, tide?, low_margin?, corridor?, ...}``.

        Lever ``RouteError`` en cas d'impossibilité."""
        raise NotImplementedError

    @abstractmethod
    def compute_manual(
        self,
        waypoints: list[tuple[float, float]],
        draft_m: float, depth_margin_m: float, lateral_margin_m: float,
        tide_m: float = 0.0,
        params: dict[str, Any] | None = None,
    ) -> dict:
        """Vérification/densification d'une route manuelle. Shape de retour
        identique à ``compute_auto``."""
        raise NotImplementedError

    def capabilities(self) -> dict[str, Any]:
        """Métadonnées affichées côté UI (moteur de sélection admin)."""
        return {
            "id": self.id,
            "version": self.version,
            "description": self.description,
            "supports_tide": True,
            "supports_manual": True,
            "supports_shallow_mode": True,
        }


__all__ = ["BaseAlgo"]
