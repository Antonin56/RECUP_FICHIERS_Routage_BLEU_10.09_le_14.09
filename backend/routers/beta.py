"""Mode test BÊTA (19/07/2026 — préparation distribution interne APK).

Objectif : permettre aux bêta-testeurs déclarés de créer des signalements
DE TEST depuis la terre, visibles par les autres comme tests (badge TEST),
et de basculer rapidement entre leurs comptes de test.

Modèle :
  - Collection `beta_testers` : { phone: "+33XXXXXXXXX", note, added_by,
    added_at }. Gérée par l'ADMIN (DEV_BYPASS_EMAILS) via les endpoints
    /beta/testers.
  - Un utilisateur est « testeur » si son téléphone figure dans la
    collection OU s'il est compte dev (is_dev_user).
  - Le testeur active/désactive son « mode test » (users.test_mode). Quand
    il est ON : geofence « en mer » bypassée à la création/confirmation,
    et le signalement créé porte `is_test: True`.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import server as srv
from core.auth import DEV_BYPASS_EMAILS, is_dev_user

logger = logging.getLogger("signalmar.beta")
router = APIRouter(tags=["beta"])


def normalize_phone(raw: str) -> Optional[str]:
    """'06 12 34 56 78' / '+33612345678' → '+33612345678' (mobiles FR)."""
    p = re.sub(r"[^\d+]", "", raw or "")
    if re.fullmatch(r"0[67]\d{8}", p):
        return "+33" + p[1:]
    if re.fullmatch(r"\+33[67]\d{8}", p):
        return p
    return None


def _is_admin(u: Optional[dict]) -> bool:
    email = ((u or {}).get("email") or "").lower().strip()
    return bool(email) and email in DEV_BYPASS_EMAILS


async def is_beta_tester(u: Optional[dict]) -> bool:
    """Testeur = compte dev OU téléphone présent dans `beta_testers`."""
    if not u:
        return False
    if is_dev_user(u):
        return True
    phone = (u.get("phone") or "").strip()
    if not phone:
        return False
    doc = await srv.db.beta_testers.find_one({"phone": phone})
    return doc is not None


async def test_mode_active(u: Optional[dict]) -> bool:
    """True si l'utilisateur est testeur ET a activé son mode test."""
    return bool((u or {}).get("test_mode")) and await is_beta_tester(u)


async def tester_phones() -> set[str]:
    docs = await srv.db.beta_testers.find({}, {"_id": 0, "phone": 1}).to_list(500)
    return {d["phone"] for d in docs}


# ── Endpoints testeur ─────────────────────────────────────────────────
@router.get("/beta/status")
async def beta_status(request: Request):
    u = await srv.current_user(request)
    tester = await is_beta_tester(u)
    return {
        "is_tester": tester,
        "is_admin": _is_admin(u),
        "test_mode": bool(u.get("test_mode")) and tester,
    }


class TestModeIn(BaseModel):
    enabled: bool


@router.post("/beta/test-mode")
async def set_test_mode(body: TestModeIn, request: Request):
    u = await srv.current_user(request)
    if not await is_beta_tester(u):
        raise HTTPException(status_code=403, detail="Réservé aux bêta-testeurs.")
    await srv.db.users.update_one(
        {"user_id": u["user_id"]}, {"$set": {"test_mode": bool(body.enabled)}}
    )
    logger.info("test_mode %s -> %s", u.get("pseudo"), body.enabled)
    return {"ok": True, "test_mode": bool(body.enabled)}


# ── Endpoints ADMIN (gestion de la liste) ─────────────────────────────
@router.get("/beta/testers")
async def list_testers(request: Request):
    u = await srv.current_user(request)
    if not _is_admin(u):
        raise HTTPException(status_code=403, detail="Réservé à l'admin.")
    docs = await srv.db.beta_testers.find({}, {"_id": 0}).to_list(500)
    # Enrichit avec le compte associé s'il existe (pseudo, test_mode).
    phones = [d["phone"] for d in docs]
    users = await srv.db.users.find(
        {"phone": {"$in": phones}},
        {"_id": 0, "phone": 1, "pseudo": 1, "test_mode": 1, "user_id": 1},
    ).to_list(500)
    by_phone = {x.get("phone"): x for x in users}
    out = []
    for d in sorted(docs, key=lambda x: x.get("added_at") or srv.now_utc()):
        acc = by_phone.get(d["phone"])
        out.append({
            "phone": d["phone"],
            "note": d.get("note") or "",
            "added_at": d.get("added_at"),
            "pseudo": (acc or {}).get("pseudo"),
            "has_account": acc is not None,
            "test_mode": bool((acc or {}).get("test_mode")),
        })
    return {"testers": out}


class TesterIn(BaseModel):
    phone: str = Field(..., description="Mobile FR : 06/07… ou +336/7…")
    note: Optional[str] = Field(default=None, max_length=60)


@router.post("/beta/testers")
async def add_tester(body: TesterIn, request: Request):
    u = await srv.current_user(request)
    if not _is_admin(u):
        raise HTTPException(status_code=403, detail="Réservé à l'admin.")
    phone = normalize_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=422, detail="Numéro de mobile FR invalide.")
    await srv.db.beta_testers.update_one(
        {"phone": phone},
        {"$set": {
            "phone": phone,
            "note": (body.note or "").strip(),
            "added_by": u["user_id"],
            "added_at": srv.now_utc(),
        }},
        upsert=True,
    )
    logger.info("beta tester added: %s (by %s)", phone, u.get("email"))
    return {"ok": True, "phone": phone}


@router.delete("/beta/testers/{phone}")
async def remove_tester(phone: str, request: Request):
    u = await srv.current_user(request)
    if not _is_admin(u):
        raise HTTPException(status_code=403, detail="Réservé à l'admin.")
    norm = normalize_phone(phone) or phone
    res = await srv.db.beta_testers.delete_one({"phone": norm})
    # Coupe aussi le mode test du compte associé (s'il existe).
    await srv.db.users.update_many({"phone": norm}, {"$set": {"test_mode": False}})
    return {"ok": True, "deleted": res.deleted_count}
