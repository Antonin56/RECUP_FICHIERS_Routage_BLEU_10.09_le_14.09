"""SignalMar — RÈGLES DE NAVIGATION du Moteur C (03/08/2026).

Charge ``config/navigation_rules.yaml`` (consignes armateur explicites) et
expose :

* :func:`get_rules` — le document YAML complet (servi tel quel par
  ``GET /api/routing/rules``) ;
* :func:`default_params` — les valeurs à plat, surchargeables moteur par
  moteur via le champ ``params`` du document ``engines`` ;
* :data:`DEPTH_PRIORITY` — contextvar lue par le noyau A* historique pour
  appliquer la RÈGLE 2 (profondeur prioritaire sur la distance). Valeur par
  défaut ``(0.0, 15.0)`` = AUCUN surcoût : les moteurs A et B sont donc
  strictement inchangés.

Ce module ne s'applique qu'au Moteur C. Les moteurs A/B sont GELÉS.
"""
from __future__ import annotations

import contextvars
from pathlib import Path
from typing import Any

import yaml

RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "navigation_rules.yaml"

#: (poids, fond de référence en m) — cf. RÈGLE 2. (0.0, …) = pas de surcoût.
DEPTH_PRIORITY = contextvars.ContextVar[tuple[float, float]](
    "sm_depth_priority", default=(0.0, 15.0),
)

_cache: dict[str, Any] | None = None


def get_rules(*, reload: bool = False) -> dict[str, Any]:
    """Document YAML des règles (mis en cache). ``{}`` si le fichier manque."""
    global _cache
    if _cache is None or reload:
        if not RULES_PATH.exists():
            _cache = {}
        else:
            _cache = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
    return _cache


def default_params() -> dict[str, Any]:
    """Aplatit toutes les clés ``rules:`` des sections en un seul dict —
    c'est le jeu de paramètres surchargeables du Moteur C."""
    out: dict[str, Any] = {}
    for section in get_rules().values():
        if isinstance(section, dict):
            for k, v in (section.get("rules") or {}).items():
                out[k] = v
    return out


def merge_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Défauts YAML + overrides du moteur (clés inconnues ignorées)."""
    p = default_params()
    if params:
        p.update({k: v for k, v in params.items() if k in p})
    return p


__all__ = ["DEPTH_PRIORITY", "RULES_PATH", "get_rules", "default_params", "merge_params"]
