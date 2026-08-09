"""SignalMar — Mécanisme de version d'app (15/07/2026, GO armateur).

Objectif : quand l'app sera sur les stores, pouvoir signaler aux
utilisateurs qu'une mise à jour est disponible (bannière) ou requise
(écran bloquant doux), SANS attendre que les stores le fassent.

Fonctionnement :
  • ``GET /api/app/version`` (public, appelé au lancement de l'app) →
    ``{latest, minimum, android_url, ios_url, message}``.
      - latest  : dernière version publiée → si version locale < latest,
        l'app affiche une bannière « Mise à jour disponible » (rejetable,
        mémorisée par version).
      - minimum : version minimale supportée → si version locale < minimum,
        l'app affiche un écran « Mise à jour requise » (bouton store +
        « Plus tard » discret — blocage DOUX : app de sécurité en mer,
        on ne verrouille jamais complètement).
  • ``POST /api/app/version`` (admin whitelist) → met à jour le document
    Mongo ``app_config/_id="version"`` sans redéploiement. C'est CE call
    qu'on fera à chaque publication d'une nouvelle version store.

Les valeurs par défaut (aucun doc en base) reflètent la version courante
du bundle (app.json expo.version) : aucune bannière tant qu'on n'a pas
explicitement publié une version supérieure.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import server as srv

logger = logging.getLogger("signalmar.app_version")
router = APIRouter(tags=["app"])

# Doit suivre expo.version de /app/frontend/app.json au moment du build.
DEFAULT_LATEST = "1.5.0"
DEFAULT_MINIMUM = "1.0.0"

# Même posture que routers/dev_switch.py : whitelist compile-time.
_ADMIN_EMAILS = {"antoninlepinay@gmail.com"}

_SEMVER_HELP = "format attendu : X.Y.Z (ex. 1.6.0)"


def _valid_semver(v: str) -> bool:
    parts = v.split(".")
    return 1 <= len(parts) <= 3 and all(p.isdigit() for p in parts)


@router.get("/app/version")
async def get_app_version():
    doc = await srv.db.app_config.find_one({"_id": "version"}) or {}
    return {
        "latest": doc.get("latest") or DEFAULT_LATEST,
        "minimum": doc.get("minimum") or DEFAULT_MINIMUM,
        "android_url": doc.get("android_url") or "",
        "ios_url": doc.get("ios_url") or "",
        "message": doc.get("message") or "",
    }


class VersionIn(BaseModel):
    latest: Optional[str] = Field(None, max_length=20)
    minimum: Optional[str] = Field(None, max_length=20)
    android_url: Optional[str] = Field(None, max_length=500)
    ios_url: Optional[str] = Field(None, max_length=500)
    message: Optional[str] = Field(None, max_length=300)


@router.post("/app/version")
async def set_app_version(body: VersionIn, request: Request):
    me = await srv.current_user(request)
    if (me.get("email") or "").lower() not in _ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="admin_only")
    updates = {k: v for k, v in body.dict().items() if v is not None}
    for key in ("latest", "minimum"):
        if key in updates and not _valid_semver(updates[key]):
            raise HTTPException(status_code=422, detail=f"{key} invalide — {_SEMVER_HELP}")
    if not updates:
        raise HTTPException(status_code=422, detail="aucun champ fourni")
    await srv.db.app_config.update_one(
        {"_id": "version"}, {"$set": updates}, upsert=True,
    )
    logger.info("app version config updated by %s: %s", me.get("email"), updates)
    return await get_app_version()
