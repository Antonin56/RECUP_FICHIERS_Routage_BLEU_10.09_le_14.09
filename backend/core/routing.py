"""SignalMar — Shim de compatibilité (31/07/2026).

Ce module conserve pour raisons de rétrocompatibilité les 5 symboles
publics historiques (``compute_route``, ``manual_route``, ``RouteError``,
``nearest_navigable``, ``shallow_legs``) + toutes les constantes de
paramétrage utilisées par les tests et scripts existants.

Le code d'origine (~1900 lignes) a été isolé dans
``core.routing_engines.algos.signalmar_v1.core`` où il continue à vivre
sans modification. Ce shim délègue simplement.

Tout NOUVEAU code doit passer par ``core.routing_engines.get_engine_or_default``
+ ``BaseAlgo.compute_auto`` plutôt que par ces fonctions directement, pour
bénéficier de la sélection multi-moteurs (A, B, futures variantes).
"""
from __future__ import annotations

# ── Ré-exports des fonctions publiques ────────────────────────────────────
from core.routing_engines.algos.signalmar_v1.core import (
    compute_route,          # noqa: F401 — API historique
    manual_route,           # noqa: F401
    RouteError,             # noqa: F401
    nearest_navigable,      # noqa: F401
    shallow_legs,           # noqa: F401
    nearest_reachable,      # noqa: F401 — utilisé par tests iter*
)

# ── Ré-exports des constantes (utilisées par routers/routing.py et tests) ─
from core.routing_engines.algos.signalmar_v1.core import (  # noqa: F401
    MAX_DIM, FINE_DIM, PAD_FRAC, PAD_MIN_DEG, FINE_PAD_MIN_DEG,
    SNAP_MAX_M, SNAP_DEPTH_TOL_M, BLOCKED_DEPTH_TOL_M, END_SNAP_MAX_M,
    TRAP_POCKET_KM2, PENALTY_K, PROFILE_STEP_M,
    FILLET_M, CORRIDOR_WIDTHS, MSG_BLOCKED,
)

# Bornes de validation (utilisées par le router FastAPI).
from core.routing_engines.algos.signalmar_v1.core import (  # noqa: F401
    DEPTH_MARGIN_MIN, DEPTH_MARGIN_MAX,
    DRAFT_MIN, DRAFT_MAX,
    LATERAL_MIN, LATERAL_MAX,
)

__all__ = [
    "compute_route", "manual_route", "RouteError",
    "nearest_navigable", "nearest_reachable", "shallow_legs",
    # constantes
    "MAX_DIM", "FINE_DIM", "PAD_FRAC", "PAD_MIN_DEG", "FINE_PAD_MIN_DEG",
    "SNAP_MAX_M", "SNAP_DEPTH_TOL_M", "BLOCKED_DEPTH_TOL_M", "END_SNAP_MAX_M",
    "TRAP_POCKET_KM2", "PENALTY_K", "PROFILE_STEP_M",
    "FILLET_M", "CORRIDOR_WIDTHS", "MSG_BLOCKED",
    "DEPTH_MARGIN_MIN", "DEPTH_MARGIN_MAX",
    "DRAFT_MIN", "DRAFT_MAX",
    "LATERAL_MIN", "LATERAL_MAX",
]
