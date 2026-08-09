"""Phase 3c — In-app notifications endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import server as srv
from core import notifications as NOTIF

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(request: Request, limit: int = NOTIF.NOTIF_LIMIT_DEFAULT, unread_only: bool = False):
    u = await srv.current_user(request)
    try:
        limit = max(1, min(int(limit), NOTIF.NOTIF_LIMIT_MAX))
    except Exception:
        limit = NOTIF.NOTIF_LIMIT_DEFAULT
    query: dict = {"user_id": u["user_id"]}
    if unread_only:
        query["read_at"] = None
    rows: list[dict] = []
    async for r in srv.db.notifications.find(query, {"_id": 0}).sort("created_at", -1).limit(limit):
        rows.append(r)
    unread = await NOTIF.unread_count(srv.db, u["user_id"])
    return {"items": rows, "unread_count": unread}


@router.get("/notifications/count")
async def unread_count_endpoint(request: Request):
    """Small polled endpoint used by the bell badge on the map header."""
    u = await srv.current_user(request)
    return {"unread_count": await NOTIF.unread_count(srv.db, u["user_id"])}


@router.post("/notifications/{notif_id}/read")
async def mark_read(notif_id: str, request: Request):
    u = await srv.current_user(request)
    now = srv.now_utc()
    res = await srv.db.notifications.update_one(
        {"id": notif_id, "user_id": u["user_id"], "read_at": None},
        {"$set": {"read_at": now}},
    )
    if res.matched_count == 0:
        # Already read or doesn't belong to caller — no-op, not an error.
        return {"ok": True}
    return {"ok": True}


@router.post("/notifications/read-all")
async def mark_all_read(request: Request):
    u = await srv.current_user(request)
    now = srv.now_utc()
    res = await srv.db.notifications.update_many(
        {"user_id": u["user_id"], "read_at": None},
        {"$set": {"read_at": now}},
    )
    return {"ok": True, "updated": res.modified_count}


@router.delete("/notifications/all")
async def clear_all(request: Request):
    u = await srv.current_user(request)
    res = await srv.db.notifications.delete_many({"user_id": u["user_id"]})
    return {"ok": True, "deleted": res.deleted_count}


@router.delete("/notifications/{notif_id}")
async def delete_one(notif_id: str, request: Request):
    u = await srv.current_user(request)
    res = await srv.db.notifications.delete_one({"id": notif_id, "user_id": u["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Notification introuvable.")
    return {"ok": True}
