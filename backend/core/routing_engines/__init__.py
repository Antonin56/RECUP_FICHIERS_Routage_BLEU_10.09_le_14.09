"""SignalMar — Package des moteurs de routage (31/07/2026)."""
from core.routing_engines.base import BaseAlgo
from core.routing_engines.algos import ALGO_REGISTRY, get_algo, list_algos
from core.routing_engines.manager import (
    DEFAULT_ALGO, DEFAULT_ENGINE_ID,
    ensure_seed, ensure_indexes,
    list_engines, get_engine, get_engine_or_default,
    duplicate_engine, rename_engine, delete_engine, set_active_flag,
    bump_usage, resolve_algo,
)

__all__ = [
    "BaseAlgo",
    "ALGO_REGISTRY", "get_algo", "list_algos",
    "DEFAULT_ALGO", "DEFAULT_ENGINE_ID",
    "ensure_seed", "ensure_indexes",
    "list_engines", "get_engine", "get_engine_or_default",
    "duplicate_engine", "rename_engine", "delete_engine", "set_active_flag",
    "bump_usage", "resolve_algo",
]
