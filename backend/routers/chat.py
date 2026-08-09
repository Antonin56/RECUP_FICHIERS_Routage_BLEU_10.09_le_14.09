"""Per-report chat messages.

Endpoints (mounted under /api):
- POST /api/reports/{rid}/messages → post a message
- GET  /api/reports/{rid}/messages → list (most recent 200)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import server as srv

router = APIRouter(tags=["chat"])


@router.post("/reports/{rid}/messages")
async def post_message(rid: str, body: "srv.MessageIn", request: Request):
    u = await srv.current_user(request)
    r = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    msg = {
        "id": srv.new_id(),
        "report_id": rid,
        "user_id": u["user_id"],
        "name": u.get("name", ""),
        "text": body.text,
        "created_at": srv.now_utc(),
    }
    await srv.db.report_messages.insert_one(msg)
    msg.pop("_id", None)
    return msg


@router.get("/reports/{rid}/messages")
async def list_messages(rid: str):
    msgs = []
    async for m in (
        srv.db.report_messages
        .find({"report_id": rid}, {"_id": 0})
        .sort("created_at", 1)
        .limit(200)
    ):
        msgs.append(m)
    return msgs
