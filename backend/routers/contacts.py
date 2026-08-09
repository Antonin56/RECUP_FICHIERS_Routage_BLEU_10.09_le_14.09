"""Phase 4.2 — Contact sync.

Endpoint that lets the app match a batch of hashed phone numbers against
the SignalMar user base. The raw numbers never leave the device: the
mobile client computes SHA-256(E.164) locally and only sends hashes.

We support up to 500 hashes per call. The response lists matched users
in an "on this app" section so the frontend can render them at the top
of the invite screen.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import server as srv
from core import points as PT

router = APIRouter(tags=["contacts"])

MAX_BATCH = 500


class ContactMatchIn(BaseModel):
    hashes: List[str] = Field(default_factory=list)


@router.post("/contacts/match")
async def contacts_match(body: ContactMatchIn, request: Request):
    """Return the SignalMar users whose phone_hash appears in the request.

    The response is intentionally slim: pseudo, avatar, rank label and
    reliability so the invite screen renders without a second round-trip.
    """
    me = await srv.current_user(request)
    hashes = [h.strip().lower() for h in (body.hashes or []) if h and isinstance(h, str)]
    # Deduplicate while preserving order (small optimisation for repeated
    # numbers stored under multiple contact labels).
    seen = set()
    dedup = []
    for h in hashes:
        if h and h not in seen:
            seen.add(h)
            dedup.append(h)
    if not dedup:
        return {"matches": []}
    if len(dedup) > MAX_BATCH:
        raise HTTPException(status_code=413, detail=f"max {MAX_BATCH} hashes per call")

    projection = {"_id": 0, "user_id": 1, "phone_hash": 1, "pseudo": 1, "picture": 1, "points": 1}
    matches = [
        u async for u in srv.db.users.find(
            {"phone_hash": {"$in": dedup}, "user_id": {"$ne": me["user_id"]}},
            projection,
        )
    ]
    out = []
    for u in matches:
        pts = int(u.get("points") or 0)
        out.append({
            "phone_hash": u.get("phone_hash"),
            "user_id": u.get("user_id"),
            "pseudo": u.get("pseudo") or "Marin",
            "picture": u.get("picture") or "",
            "rank_label": srv.marine_rank(pts)[1],
            "reliability_score": PT.read_reliability(u) if hasattr(PT, "read_reliability") else None,
        })
    return {"matches": out}


async def ensure_indexes(db) -> None:
    # sparse index because most users don't have a phone yet on legacy rows
    await db.users.create_index("phone_hash", sparse=True)
    # Phase K.20 — Repair the legacy `phone_1` unique index. The old one
    # was `unique + sparse` but Mongo's `sparse` semantics only skip
    # docs that MISS the field, not those that hold `phone: null`. As a
    # result, sign-ups without a phone would 500 with E11000 as soon
    # as a second null-phone account existed. Drop and recreate with a
    # partial filter that only enforces uniqueness for STRING phones.
    try:
        info = await db.users.index_information()
        current = info.get("phone_1")
        needs_rebuild = bool(current) and not (
            (current.get("partialFilterExpression") or {}).get("phone")
        )
        if needs_rebuild:
            await db.users.drop_index("phone_1")
        if needs_rebuild or "phone_1" not in info:
            await db.users.create_index(
                "phone",
                unique=True,
                partialFilterExpression={"phone": {"$type": "string"}},
                name="phone_1",
            )
    except Exception:
        # Never let index maintenance kill boot — logged elsewhere.
        pass


async def backfill_phone_hashes(db, batch_size: int = 200) -> int:
    """One-shot idempotent backfill: compute phone_hash for existing users
    that have a raw phone but no hash yet. Safe to re-run."""
    import hashlib
    cursor = db.users.find(
        {"phone": {"$exists": True, "$ne": None}, "phone_hash": {"$exists": False}},
        {"_id": 0, "user_id": 1, "phone": 1},
    )
    n = 0
    async for u in cursor:
        phone = u.get("phone")
        if not phone:
            continue
        h = hashlib.sha256(str(phone).encode("utf-8")).hexdigest()
        await db.users.update_one({"user_id": u["user_id"]}, {"$set": {"phone_hash": h}})
        n += 1
        if n >= batch_size:
            break
    return n
