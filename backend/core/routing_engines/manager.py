"""SignalMar — Gestionnaire des MOTEURS de routage (31/07/2026).

Un « moteur » est un profil nommé stocké dans MongoDB, lié à un algo Python
(via son id stable ``algo``) et à d'éventuels overrides de paramètres. C'est
l'entité que l'utilisateur voit et manipule depuis son profil : liste,
sélection, duplication, renommage, suppression.

Schéma d'un document ``engines`` :

.. code-block:: python

    {
      "id": "engine_a",           # slug stable (unique)
      "name": "Moteur A",         # affichage, renommable
      "description": "...",       # facultatif
      "algo": "signalmar.v1",     # clé dans ALGO_REGISTRY
      "params": {},               # overrides des paramètres de l'algo
      "active": True,             # visible dans l'UI
      "built_in": True,           # A + B seeds, non supprimables
      "parent_id": None,          # slug du moteur d'origine si dupliqué
      "created_at": datetime,
      "updated_at": datetime,
      "usage_count": 0,           # incrémenté à chaque route calculée
    }
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from core.routing_engines.algos import ALGO_REGISTRY, get_algo

logger = logging.getLogger("signalmar.routing.engines")


# ── Identifiants ──────────────────────────────────────────────────────────
# 02/08/2026 — l'ID d'un moteur est VOLONTAIREMENT indépendant de son nom :
# l'armateur renomme librement ses moteurs, l'ID reste la clé de traçabilité
# (affiché dans le profil et sur chaque route calculée). On poursuit donc la
# convention alphabétique des built-in : engine_a, engine_b → engine_c, …
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _next_engine_id(taken: set[str]) -> str:
    """Prochain ID libre de la série ``engine_c``, ``engine_d``, … puis
    ``engine_aa`` quand l'alphabet est épuisé."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    for ch in letters:
        cand = f"engine_{ch}"
        if cand not in taken:
            return cand
    for first in letters:
        for second in letters:
            cand = f"engine_{first}{second}"
            if cand not in taken:
                return cand
    return "engine_" + secrets.token_hex(3)


def _valid_slug(slug: str) -> bool:
    return bool(_ID_RE.match(slug))


# ── Constantes seed ───────────────────────────────────────────────────────
DEFAULT_ALGO = "signalmar.v1"
DEFAULT_ENGINE_ID = "engine_a"

_BUILTIN_SEEDS = [
    {
        "id": "engine_a",
        "name": "Moteur A",
        "description": (
            "Moteur historique SignalMar (référence de non-régression). "
            "Ne pas modifier."
        ),
        "algo": DEFAULT_ALGO,
        "params": {},
        "active": True,
        "built_in": True,
        "parent_id": None,
    },
    {
        "id": "engine_b",
        "name": "Moteur B",
        "description": (
            "Bac à sable : moteur historique + correctif « écart minimal aux "
            "balises » (02/08 — Fernais 25). Sert à tester les variantes sans "
            "toucher au Moteur A."
        ),
        "algo": "signalmar.v2",
        "params": {},
        "active": True,
        "built_in": True,
        "parent_id": "engine_a",
    },
    # 03/08/2026 (consignes armateur) — MOTEUR C : nouveau jeu de règles
    # STRICTES (balisage prioritaire, sens conventionnel forcé mer → terre,
    # profondeur prioritaire sur la distance, marge 50 m → 20 m, jamais de
    # « Passage impossible »). Les Moteurs A et B restent GELÉS.
    {
        "id": "engine_c",
        "name": "Moteur C",
        "description": (
            "Règles de navigation strictes du 03/08 : sens conventionnel FORCÉ "
            "(mer → terre, même tracé dans les deux sens), rouges à bâbord / "
            "vertes à tribord, profondeur prioritaire sur la distance, marge "
            "latérale 50 m réductible à 20 m, et jamais de « Passage "
            "impossible » (tronçons rouges à la place)."
        ),
        "algo": "signalmar.v3",
        "params": {},
        "active": True,
        "built_in": True,
        "parent_id": None,
    },
]


# ── CRUD ──────────────────────────────────────────────────────────────────
async def ensure_seed(db) -> None:
    """Idempotent : crée les moteurs A + B s'ils manquent, laisse les autres
    tels quels. À appeler au démarrage.

    02/08/2026 — REBIND des built-in : si le code lie désormais un moteur
    built-in à un autre algo (ex. Moteur B → ``signalmar.v2`` pour le
    correctif « écart minimal aux balises »), on met à jour le document
    existant (algo + description). Les moteurs DUPLIQUÉS par l'armateur ne
    sont jamais touchés — ils gardent l'algo choisi à leur création."""
    now = datetime.now(timezone.utc)
    for seed in _BUILTIN_SEEDS:
        exists = await db.engines.find_one(
            {"id": seed["id"]}, {"_id": 1, "algo": 1},
        )
        if exists:
            if exists.get("algo") != seed["algo"]:
                await db.engines.update_one(
                    {"id": seed["id"]},
                    {"$set": {
                        "algo": seed["algo"],
                        "description": seed["description"],
                        "updated_at": now,
                    }},
                )
                logger.info(
                    "engine %s rebound: %s → %s",
                    seed["id"], exists.get("algo"), seed["algo"],
                )
            continue
        await db.engines.insert_one({
            **seed, "created_at": now, "updated_at": now, "usage_count": 0,
        })
        logger.info("engine seeded: %s (%s)", seed["id"], seed["name"])


async def ensure_indexes(db) -> None:
    await db.engines.create_index("id", unique=True)
    await db.engines.create_index([("active", 1), ("name", 1)])


async def list_engines(db, *, only_active: bool = True) -> list[dict]:
    q = {"active": True} if only_active else {}
    cursor = db.engines.find(q, {"_id": 0}).sort([("built_in", -1), ("created_at", 1)])
    return await cursor.to_list(200)


async def get_engine(db, engine_id: str) -> dict | None:
    return await db.engines.find_one({"id": engine_id}, {"_id": 0})


async def get_engine_or_default(db, engine_id: str | None) -> dict:
    """Résout un ``engine_id`` en un document existant. Fallback vers le
    moteur par défaut (``engine_a``) si l'ID est manquant/invalide/inconnu.
    N'échoue jamais — les routes doivent toujours pouvoir se calculer."""
    if engine_id:
        doc = await get_engine(db, engine_id)
        if doc and doc.get("active"):
            return doc
    doc = await get_engine(db, DEFAULT_ENGINE_ID)
    if doc:
        return doc
    # Cas de bootstrap paranoïaque : moteur A non seedé encore. On retourne
    # un doc « en mémoire » minimal pour que le calcul aboutisse.
    return {
        "id": DEFAULT_ENGINE_ID, "name": "Moteur A", "algo": DEFAULT_ALGO,
        "params": {}, "active": True, "built_in": True,
    }


async def duplicate_engine(
    db, *, source_id: str, name: str, description: str | None = None,
) -> dict:
    """Clone profond d'un moteur (params inclus). Le clone est ``active=True``,
    ``built_in=False`` et référence sa source via ``parent_id``."""
    src = await get_engine(db, source_id)
    if src is None:
        raise KeyError(f"Moteur source introuvable : {source_id!r}.")

    taken = {d["id"] async for d in db.engines.find({}, {"id": 1})}
    slug = _next_engine_id(taken)
    now = datetime.now(timezone.utc)
    clone = {
        "id": slug,
        "name": name.strip()[:80] or f"Copie de {src.get('name', source_id)}",
        "description": (description or f"Clone de {src.get('name', source_id)}")[:400],
        "algo": src["algo"],
        "params": dict(src.get("params") or {}),  # copie superficielle suffisante
        "active": True,
        "built_in": False,
        "parent_id": src["id"],
        "created_at": now,
        "updated_at": now,
        "usage_count": 0,
    }
    await db.engines.insert_one(clone)
    logger.info(
        "engine duplicated: %s → %s (algo=%s)",
        source_id, slug, src["algo"],
    )
    return {k: v for k, v in clone.items() if k != "_id"}


async def rename_engine(db, engine_id: str, name: str,
                        description: str | None = None) -> dict:
    doc = await get_engine(db, engine_id)
    if doc is None:
        raise KeyError(f"Moteur introuvable : {engine_id!r}.")
    update = {"name": name.strip()[:80], "updated_at": datetime.now(timezone.utc)}
    if description is not None:
        update["description"] = description.strip()[:400]
    if not update["name"]:
        raise ValueError("Le nom du moteur ne peut pas être vide.")
    await db.engines.update_one({"id": engine_id}, {"$set": update})
    return (await get_engine(db, engine_id)) or {}


async def delete_engine(db, engine_id: str) -> None:
    """Suppression SAFE (option A validée par l'armateur) : refus si le moteur
    a servi à générer une route enregistrée (``saved_routes`` ou
    ``computed_routes``). Les built-in ne peuvent jamais être supprimés."""
    doc = await get_engine(db, engine_id)
    if doc is None:
        raise KeyError(f"Moteur introuvable : {engine_id!r}.")
    if doc.get("built_in"):
        raise ValueError("Les moteurs A et B (built-in) ne peuvent pas être supprimés.")
    # Vérification usage (voir aussi le compteur usage_count mais on prend la
    # source de vérité authoritative : présence dans les collections).
    used_saved = await db.saved_routes.find_one({"engine_id": engine_id}, {"_id": 1})
    used_computed = await db.computed_routes.find_one({"engine_id": engine_id}, {"_id": 1})
    if used_saved or used_computed:
        raise ValueError(
            "Ce moteur a déjà servi à générer une route enregistrée. "
            "Pour préserver l'historique, il ne peut pas être supprimé — "
            "vous pouvez le désactiver."
        )
    await db.engines.delete_one({"id": engine_id})
    logger.info("engine deleted: %s", engine_id)


async def set_active_flag(db, engine_id: str, active: bool) -> dict:
    """Active/désactive un moteur (les built-in restent toujours actifs)."""
    doc = await get_engine(db, engine_id)
    if doc is None:
        raise KeyError(f"Moteur introuvable : {engine_id!r}.")
    if doc.get("built_in") and not active:
        raise ValueError("Les moteurs A et B (built-in) ne peuvent pas être désactivés.")
    await db.engines.update_one(
        {"id": engine_id},
        {"$set": {"active": bool(active), "updated_at": datetime.now(timezone.utc)}},
    )
    return (await get_engine(db, engine_id)) or {}


async def bump_usage(db, engine_id: str) -> None:
    """Incrémente le compteur d'usage (best-effort, jamais bloquant)."""
    try:
        await db.engines.update_one(
            {"id": engine_id}, {"$inc": {"usage_count": 1}},
        )
    except Exception:  # noqa: BLE001
        pass


# ── Exécution ─────────────────────────────────────────────────────────────
def resolve_algo(engine_doc: dict):
    """Retourne l'instance ``BaseAlgo`` liée au moteur. Fallback algo par
    défaut si le binding est cassé (algo supprimé en code)."""
    algo_id = (engine_doc or {}).get("algo") or DEFAULT_ALGO
    try:
        return get_algo(algo_id)
    except KeyError:
        logger.warning(
            "engine %s pointe vers algo inconnu %s → fallback %s",
            engine_doc.get("id"), algo_id, DEFAULT_ALGO,
        )
        return get_algo(DEFAULT_ALGO)


__all__ = [
    "DEFAULT_ALGO", "DEFAULT_ENGINE_ID",
    "ensure_seed", "ensure_indexes",
    "list_engines", "get_engine", "get_engine_or_default",
    "duplicate_engine", "rename_engine", "delete_engine", "set_active_flag",
    "bump_usage", "resolve_algo",
]
