"""SignalMar — Registre des algorithmes de routage (31/07/2026).

Chaque algorithme s'enregistre ici sous une **clé stable** utilisée par les
documents Moteur (champ ``algo``). Ne jamais renommer une clé existante
sous peine d'invalider les liens des moteurs et des routes historiques.
"""
from __future__ import annotations

from core.routing_engines.base import BaseAlgo
from core.routing_engines.algos.signalmar_v1 import SignalmarV1
from core.routing_engines.algos.signalmar_v2 import SignalmarV2
from core.routing_engines.algos.signalmar_v3 import SignalmarV3
from core.routing_engines.algos.signalmar_v4 import SignalmarV4
from core.routing_engines.algos.signalmar_v5 import SignalmarV5
from core.routing_engines.algos.signalmar_v6 import SignalmarV6
from core.routing_engines.algos.signalmar_h import SignalmarH
# 27/08/2026 (ordre armateur — maintenance critique) : Moteur F GELÉ dans
# core/nav/engine_f_frozen.py (référence immuable) et Moteur I (copie de
# travail) dans core/nav/engine_i.py. Imports APRÈS les algos v1-h (leurs
# modules doivent déjà être initialisés — pas de circularité).
from core.nav.engine_f_frozen import EngineFFrozen
from core.nav.engine_i import EngineI

#: Clé stable → instance singleton de l'algo (les algos SignalMar sont
#: stateless au niveau instance — la vraie « state » est le module ``core``
#: lui-même, cache numba compris).
ALGO_REGISTRY: dict[str, BaseAlgo] = {
    SignalmarV1.id: SignalmarV1(),
    SignalmarV2.id: SignalmarV2(),
    SignalmarV3.id: SignalmarV3(),
    SignalmarV4.id: SignalmarV4(),
    SignalmarV5.id: SignalmarV5(),
    SignalmarV6.id: SignalmarV6(),
    SignalmarH.id: SignalmarH(),
    EngineFFrozen.id: EngineFFrozen(),
    EngineI.id: EngineI(),
}


def get_algo(algo_id: str) -> BaseAlgo:
    """Résout une clé d'algo → instance. Lève ``KeyError`` si inconnu."""
    algo = ALGO_REGISTRY.get(algo_id)
    if algo is None:
        raise KeyError(f"Algorithme inconnu : {algo_id!r}. "
                       f"Disponibles : {sorted(ALGO_REGISTRY)}")
    return algo


def list_algos() -> list[dict]:
    """Métadonnées de tous les algos disponibles (pour l'UI admin)."""
    return [algo.capabilities() for algo in ALGO_REGISTRY.values()]


__all__ = ["ALGO_REGISTRY", "get_algo", "list_algos"]
