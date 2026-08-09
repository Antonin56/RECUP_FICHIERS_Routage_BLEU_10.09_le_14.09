"""Invitations de parrainage par téléphone (10/07/2026).

Quand un parrain envoie ses SMS d'invitation depuis l'écran /share-invite,
l'app enregistre ici les numéros invités (HASHES SHA-256 d'E.164 — les
numéros bruts ne quittent jamais le téléphone du parrain). À l'inscription,
le filleul peut alors retrouver automatiquement la ou les invitations en
cours sur SON numéro et choisir son parrain (définitif).

Cycle de vie d'une invitation :
    * créée/rafraîchie à l'envoi du SMS (une par couple parrain+numéro) ;
    * expire après 60 jours (purge paresseuse à la lecture) ;
    * supprimée pour ce numéro dès que le filleul crée son compte
      (hook dans routers/auth.py).

Endpoints :
    POST /referral/invitations      (auth)   — enregistrer des invitations.
    POST /referral/pending          (public) — invitations en cours pour un n°.
    POST /referral/resolve-sponsor  (public) — retrouver un parrain à partir
        des hashes d'un contact choisi dans le carnet du filleul.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import server as srv
from core import referral as REF
from core.friends import normalize_phone

router = APIRouter(tags=["referral"])

INVITE_TTL_SECONDS = 60 * 24 * 3600  # 60 jours (validé le 10/07/2026)
MAX_BATCH = 100


class InvitationsIn(BaseModel):
    phone_hashes: List[str] = Field(default_factory=list)


class PendingIn(BaseModel):
    phone: str = Field(..., max_length=24)


class ResolveIn(BaseModel):
    phone_hashes: List[str] = Field(default_factory=list)


async def _sponsor_payload(user: dict) -> dict:
    code = user.get("referral_code") or await REF.ensure_referral_code(
        srv.db, user["user_id"],
    )
    return {
        "pseudo": user.get("pseudo") or user.get("name") or "Marin",
        "picture": user.get("picture") or "",
        "referral_code": code or "",
    }


@router.post("/referral/invitations")
async def create_invitations(body: InvitationsIn, request: Request):
    """Enregistre (upsert) les invitations du parrain courant pour une liste
    de numéros hachés. Rafraîchit l'expiration si l'invitation existe déjà."""
    me = await srv.current_user(request)
    hashes = [h for h in body.phone_hashes if isinstance(h, str) and len(h) == 64]
    hashes = list(dict.fromkeys(hashes))[:MAX_BATCH]
    if not hashes:
        return {"created": 0}
    now = int(time.time())
    expires = now + INVITE_TTL_SECONDS
    # Le parrain ne s'invite pas lui-même.
    hashes = [h for h in hashes if h != me.get("phone_hash")]
    for h in hashes:
        await srv.db.referral_invitations.update_one(
            {"referrer_user_id": me["user_id"], "phone_hash": h},
            {
                "$set": {"created_at": now, "expires_at": expires},
                "$setOnInsert": {
                    "invitation_id": "ri_" + uuid.uuid4().hex[:12],
                    "referrer_user_id": me["user_id"],
                    "phone_hash": h,
                },
            },
            upsert=True,
        )
    srv.logger.info("referral invitations: %s → %d numéros", me["user_id"], len(hashes))
    return {"created": len(hashes)}


@router.post("/referral/pending")
async def pending_invitations(body: PendingIn, request: Request):
    """Invitations de parrainage en cours pour ce numéro (appelé à
    l'inscription, AVANT authentification — ne renvoie que pseudo/avatar/code).
    Purge paresseuse des invitations expirées au passage."""
    phone = normalize_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=422, detail="Numéro invalide")
    phone_hash = hashlib.sha256(phone.encode("utf-8")).hexdigest()
    now = int(time.time())
    await srv.db.referral_invitations.delete_many({"expires_at": {"$lt": now}})
    docs = [
        d async for d in srv.db.referral_invitations.find(
            {"phone_hash": phone_hash, "expires_at": {"$gte": now}},
            {"_id": 0},
        ).sort("created_at", -1).limit(10)
    ]
    if not docs:
        return {"invitations": []}
    referrer_ids = list({d["referrer_user_id"] for d in docs})
    users = {
        u["user_id"]: u async for u in srv.db.users.find(
            {"user_id": {"$in": referrer_ids}},
            {"_id": 0, "user_id": 1, "pseudo": 1, "name": 1, "picture": 1,
             "referral_code": 1},
        )
    }
    out = []
    for d in docs:
        u = users.get(d["referrer_user_id"])
        if not u:
            continue
        payload = await _sponsor_payload(u)
        payload["invited_at"] = d.get("created_at")
        out.append(payload)
    return {"invitations": out}


@router.post("/referral/resolve-sponsor")
async def resolve_sponsor(body: ResolveIn, request: Request):
    """Retrouve un parrain à partir des hashes du contact que le filleul a
    choisi dans SON carnet (bouton « Rechercher dans mes contacts » à
    l'inscription). Public mais ne renvoie que pseudo/avatar/code."""
    hashes = [h for h in body.phone_hashes if isinstance(h, str) and len(h) == 64]
    hashes = list(dict.fromkeys(hashes))[:10]
    if not hashes:
        return {"sponsors": []}
    out = []
    async for u in srv.db.users.find(
        {"phone_hash": {"$in": hashes}},
        {"_id": 0, "user_id": 1, "pseudo": 1, "name": 1, "picture": 1,
         "referral_code": 1},
    ).limit(5):
        out.append(await _sponsor_payload(u))
    return {"sponsors": out}


async def delete_for_phone_hash(db, phone_hash: Optional[str]) -> None:
    """Hook inscription : le filleul a créé son compte (parrain choisi ou
    non) → toutes ses invitations en attente sont consommées."""
    if not phone_hash:
        return
    try:
        await db.referral_invitations.delete_many({"phone_hash": phone_hash})
    except Exception as e:  # best-effort
        srv.logger.warning("referral_invitations cleanup failed: %s", e)


async def ensure_indexes(db) -> None:
    await db.referral_invitations.create_index(
        [("referrer_user_id", 1), ("phone_hash", 1)], unique=True,
    )
    await db.referral_invitations.create_index("phone_hash")
    await db.referral_invitations.create_index("expires_at")
