"""SignalMar — Endpoints multi-moteurs de routage (01/08/2026).

Fournit :
 * ``GET /api/routing/engines`` : liste des moteurs disponibles (lecture
   pour tous les utilisateurs — permet de peupler le sélecteur dans le
   profil).
 * ``POST /api/routing/engines/duplicate`` (admin) : clone un moteur.
 * ``PATCH /api/routing/engines/{id}`` (admin) : renommage + description.
 * ``DELETE /api/routing/engines/{id}`` (admin) : suppression SAFE
   (refusée si le moteur a servi à générer une route enregistrée).
 * ``POST /api/routing/engines/{id}/active`` (admin) : (dés)activation.
 * ``POST /api/user/active-engine`` : chaque utilisateur choisit son moteur.
 * ``GET /api/routing/algos`` : listing des algorithmes Python disponibles
   (info debug / support).

Les MOTEURS built-in (Moteur A et Moteur B, seedés au démarrage) ne peuvent
pas être supprimés ni désactivés.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import server as srv
from core.auth import current_user
from core.nav_rules import default_params, get_rules
from core.routing_engines import (
    duplicate_engine, get_engine, list_engines, list_algos,
    rename_engine, delete_engine, set_active_flag,
    DEFAULT_ENGINE_ID,
)
from core.support_admin import is_signalmar_admin

logger = logging.getLogger("signalmar.routing.engines_api")
router = APIRouter(prefix="/routing", tags=["routing-engines"])


def _require_admin(user: dict) -> None:
    if not is_signalmar_admin(user):
        raise HTTPException(403, "Fonction réservée au compte SignalMar admin.")


# ── Modèles Pydantic ──────────────────────────────────────────────────────
class DuplicateIn(BaseModel):
    source_id: str = Field(..., min_length=1, max_length=48)
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = Field(None, max_length=400)


class RenameIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = Field(None, max_length=400)


class ActiveFlagIn(BaseModel):
    active: bool


class UserActiveEngineIn(BaseModel):
    engine_id: str = Field(..., min_length=1, max_length=48)


# ── Endpoints ─────────────────────────────────────────────────────────────
@router.get("/engines")
async def api_list_engines(
    include_inactive: bool = False,
    user: dict = Depends(current_user),
):
    """Liste des moteurs (lecture ouverte à tous : sélecteur du profil).
    14/08 (audit QA FND-004) — ``?include_inactive=true`` (admin) liste AUSSI
    les moteurs désactivés : un moteur désactivé n'est plus irrécupérable."""
    admin = is_signalmar_admin(user)
    engines = await list_engines(
        srv.db, only_active=not (include_inactive and admin))
    return {
        "engines": engines,
        "default_id": DEFAULT_ENGINE_ID,
        "active_id": (user or {}).get("active_engine_id") or DEFAULT_ENGINE_ID,
        "is_admin": admin,
    }


@router.get("/algos")
async def api_list_algos(user: dict = Depends(current_user)):
    """Algos Python disponibles (info debug/support). Admin uniquement."""
    _require_admin(user)
    return {"algos": list_algos()}


@router.get("/rules")
async def api_routing_rules(user: dict = Depends(current_user)):
    """03/08/2026 — RÈGLES DE NAVIGATION du Moteur C, telles qu'écrites dans
    ``config/navigation_rules.yaml`` (source de vérité lisible des consignes
    armateur : balisage, profondeur, marge latérale, jamais d'échec).
    Lecture ouverte : l'app les affiche dans la fiche du moteur."""
    return {"rules": get_rules(), "params": default_params()}


@router.post("/engines/duplicate")
async def api_duplicate_engine(body: DuplicateIn, user: dict = Depends(current_user)):
    _require_admin(user)
    try:
        clone = await duplicate_engine(
            srv.db, source_id=body.source_id.strip(),
            name=body.name.strip(), description=body.description,
        )
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "engine": clone}


@router.patch("/engines/{engine_id}")
async def api_rename_engine(engine_id: str, body: RenameIn,
                             user: dict = Depends(current_user)):
    _require_admin(user)
    try:
        doc = await rename_engine(srv.db, engine_id.strip(), body.name, body.description)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "engine": doc}


@router.delete("/engines/{engine_id}")
async def api_delete_engine(engine_id: str, user: dict = Depends(current_user)):
    _require_admin(user)
    try:
        await delete_engine(srv.db, engine_id.strip())
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True}


@router.post("/engines/{engine_id}/active")
async def api_set_active(engine_id: str, body: ActiveFlagIn,
                          user: dict = Depends(current_user)):
    _require_admin(user)
    try:
        doc = await set_active_flag(srv.db, engine_id.strip(), body.active)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "engine": doc}


# Placé sous /routing pour cohérence — mais accessible aussi via alias
# /user/active-engine (déclaré séparément pour ne pas casser une éventuelle
# route utilisateur future). Ici : préférence PERSONNELLE de l'utilisateur.
@router.post("/user/active-engine")
async def api_set_user_active_engine(body: UserActiveEngineIn,
                                      user: dict = Depends(current_user)):
    """Chaque utilisateur choisit le moteur qu'il souhaite utiliser par
    défaut pour ses propres calculs de route. Persistance sur le doc user."""
    engine_id = body.engine_id.strip()
    doc = await get_engine(srv.db, engine_id)
    if doc is None or not doc.get("active"):
        raise HTTPException(404, "Moteur inconnu ou désactivé.")
    await srv.db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "active_engine_id": engine_id,
            "active_engine_updated_at": datetime.now(timezone.utc),
        }},
    )
    logger.info("user %s active engine → %s", user.get("user_id"), engine_id)
    return {"ok": True, "engine_id": engine_id, "engine_name": doc.get("name")}
