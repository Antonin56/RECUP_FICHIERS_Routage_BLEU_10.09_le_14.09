"""Phase 3b — Friend request / accept / reject / search endpoints.

Mounted under /api. All endpoints require authentication.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import server as srv
from core import friends as FR
from core import points as PT
from core import referral as REF

router = APIRouter(tags=["friends"])


# ── payloads ──────────────────────────────────────────────────────────────
class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=64)


class RequestIn(BaseModel):
    to_user_id: str = Field(min_length=1, max_length=64)


# ── helpers ───────────────────────────────────────────────────────────────
def _public_user(u: dict) -> dict:
    """Compact projection used everywhere friends are surfaced."""
    return {
        "user_id": u.get("user_id"),
        "pseudo": u.get("pseudo") or u.get("name") or "Marin",
        "picture": u.get("picture", ""),
        "rank_label": srv.marine_rank(int(u.get("points", 0)))[1],
        "points": int(u.get("points", 0)),
        "reliability_score": PT.read_reliability(u),
        "referral_bonus_paid": bool(u.get("referral_bonus_paid")),
        "created_at": u.get("created_at"),
        "last_open_day": u.get("last_open_day"),
    }


# ── endpoints ─────────────────────────────────────────────────────────────
@router.post("/friends/search")
async def friends_search(body: SearchIn, request: Request):
    """Search by email, phone (any format) or referral code — one hit max."""
    u = await srv.current_user(request)
    target = await FR.search_user(srv.db, body.query)
    if not target or target.get("user_id") == u["user_id"]:
        return {"found": None}
    # Enrich with the current relationship so the client can render the right
    # CTA ("Ajouter", "Demande envoyée", "Déjà amis", "Accepter la demande").
    is_friend = await FR.are_friends(srv.db, u["user_id"], target["user_id"])
    outgoing = await srv.db.friend_requests.find_one({
        "from_user_id": u["user_id"],
        "to_user_id": target["user_id"],
        "status": "pending",
    }, {"_id": 0})
    incoming = await srv.db.friend_requests.find_one({
        "from_user_id": target["user_id"],
        "to_user_id": u["user_id"],
        "status": "pending",
    }, {"_id": 0})
    return {
        "found": _public_user(target),
        "relationship": (
            "friends" if is_friend
            else "outgoing_pending" if outgoing
            else "incoming_pending" if incoming
            else "none"
        ),
        "request_id": (
            (outgoing or {}).get("id") or (incoming or {}).get("id")
        ),
    }


@router.post("/friends/request")
async def send_request(body: RequestIn, request: Request):
    """Send a friend request. Idempotent w.r.t existing friendship & pending."""
    u = await srv.current_user(request)
    if body.to_user_id == u["user_id"]:
        raise HTTPException(status_code=422, detail="Impossible de s'ajouter soi-même.")
    target = await srv.db.users.find_one({"user_id": body.to_user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    req = await FR.create_request(srv.db, u["user_id"], body.to_user_id, source="search")
    if not req:
        return {"ok": True, "already_friends": True}
    # Push notif to the recipient (fire-and-forget, never raises).
    try:
        await srv.send_push(
            recipients=[body.to_user_id],
            data={
                "title": "Demande d'ami",
                "message": f"{u.get('pseudo') or u.get('name') or 'Un marin'} souhaite vous ajouter en ami.",
                "action_url": "/profile/friends",
            },
            idempotency_key=f"friend_req:{req['id']}",
        )
    except Exception as e:
        srv.logger.warning("push friend request failed: %s", e)
    return {"ok": True, "request": req}


@router.get("/friends/pending")
async def list_pending(request: Request):
    """Incoming + outgoing pending requests (for the badge / list UI)."""
    u = await srv.current_user(request)
    inc: list[dict] = []
    out: list[dict] = []
    async for r in srv.db.friend_requests.find(
        {"to_user_id": u["user_id"], "status": "pending"}, {"_id": 0},
    ).sort("created_at", -1):
        sender = await srv.db.users.find_one({"user_id": r["from_user_id"]}, {"_id": 0})
        if sender:
            inc.append({**r, "user": _public_user(sender)})
    async for r in srv.db.friend_requests.find(
        {"from_user_id": u["user_id"], "status": "pending"}, {"_id": 0},
    ).sort("created_at", -1):
        target = await srv.db.users.find_one({"user_id": r["to_user_id"]}, {"_id": 0})
        if target:
            out.append({**r, "user": _public_user(target)})
    return {"incoming": inc, "outgoing": out}


@router.post("/friends/request/{req_id}/accept")
async def accept_req(req_id: str, request: Request):
    """Accept a pending incoming request → link both users bidirectionally.

    V3b — also arm the +20 grade bonus: if the receiver has never been
    referred before, treat the sender as their referrer so the existing
    ``pay_referral_bonus`` logic fires on the receiver's first confirmed
    report. This replaces the referral-code entry-point and unifies both
    discovery paths under a single bonus rule.
    """
    u = await srv.current_user(request)
    req = await FR.accept_request(srv.db, req_id, u["user_id"])
    if not req:
        raise HTTPException(status_code=404, detail="Demande introuvable ou déjà traitée.")
    # Arm bonus for the receiver (u) if they haven't been referred yet AND
    # haven't already claimed the one-shot bonus.
    receiver = await srv.db.users.find_one(
        {"user_id": u["user_id"]},
        {"_id": 0, "referrer_user_id": 1, "referral_bonus_paid": 1},
    ) or {}
    if not receiver.get("referrer_user_id") and not receiver.get("referral_bonus_paid"):
        await srv.db.users.update_one(
            {"user_id": u["user_id"]},
            {"$set": {
                "referrer_user_id": req["from_user_id"],
                "referral_bonus_paid": False,
            }},
        )
    # Push notif back to the sender.
    try:
        await srv.send_push(
            recipients=[req["from_user_id"]],
            data={
                "title": "Demande acceptée",
                "message": f"{u.get('pseudo') or u.get('name') or 'Votre ami'} a accepté votre demande d'ami \U0001F389",
                "action_url": "/profile/friends",
            },
            idempotency_key=f"friend_acc:{req_id}",
        )
    except Exception as e:
        srv.logger.warning("push accept failed: %s", e)
    return {"ok": True}


@router.post("/friends/request/{req_id}/reject")
async def reject_req(req_id: str, request: Request):
    u = await srv.current_user(request)
    ok = await FR.reject_request(srv.db, req_id, u["user_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Demande introuvable.")
    return {"ok": True}


@router.get("/friends/list")
async def list_friends_v2(request: Request):
    """Return the caller's accepted friends (bidirectional list)."""
    u = await srv.current_user(request)
    me = await srv.db.users.find_one({"user_id": u["user_id"]}, {"_id": 0, "friends": 1})
    ids = list((me or {}).get("friends") or [])
    if not ids:
        # Backfill legacy referred users so the UI has content immediately.
        legacy = await REF.list_friends(srv.db, u["user_id"])
        for f in legacy:
            await FR.link_bidirectional(srv.db, u["user_id"], f["user_id"])
        me = await srv.db.users.find_one({"user_id": u["user_id"]}, {"_id": 0, "friends": 1})
        ids = list((me or {}).get("friends") or [])
    friends: list[dict] = []
    async for f in srv.db.users.find({"user_id": {"$in": ids}}, {"_id": 0}):
        friends.append(_public_user(f))
    friends.sort(key=lambda f: (f.get("pseudo") or "").lower())
    return {"items": friends}
