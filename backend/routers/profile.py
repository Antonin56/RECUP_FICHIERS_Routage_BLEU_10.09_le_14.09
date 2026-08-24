"""Profile management — pagination, avatar, location, preferences.

Endpoints (mounted under /api):
- GET  /api/profile/me              → user + paginated history (Phase E Lot 2)
- POST /api/profile/avatar          → base64 → JPEG 256×256
- POST /api/profile/location        → push GPS for proximity targeting
- PUT  /api/profile/preferences     → notify_radius_km / muted_types
- POST /api/profile/ping-open       → V1.2 daily/streak reward + inactivity penalty
- GET  /api/profile/points-history  → V1.2 last N gamification events
"""
from __future__ import annotations

import base64
import io
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from PIL import Image

import server as srv
from core import points as PT
from core import referral as REF

router = APIRouter(tags=["profile"])


@router.get("/profile/me")
async def profile_me(request: Request, limit: int = 5, offset: int = 0):
    """Return profile + paginated history.

    Pagination caps: limit ∈ [1, 20], offset ∈ [0, 19] (max 4 pages × 5 = 20).
    """
    u = await srv.current_user(request)
    # Clamp pagination params so the UI cannot accidentally pull huge pages.
    try:
        limit = max(1, min(int(limit), 20))
    except Exception:
        limit = 5
    try:
        offset = max(0, min(int(offset), 19))
    except Exception:
        offset = 0

    # Total reports authored by user (capped at 20 for the UI history list).
    total_reports = await srv.db.reports.count_documents(
        {"author_id": u["user_id"]}
    )
    history_total = min(total_reports, 20)

    history_raw: list[dict] = []
    cursor = (
        srv.db.reports.find({"author_id": u["user_id"]}, {"_id": 0})
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )
    async for r in cursor:
        history_raw.append(r)
    await srv.enrich_authors(history_raw)
    history = [srv.serialize_report(r, u["user_id"]) for r in history_raw]
    confirms = 0
    async for _ in srv.db.reports.find(
        {"confirmations": u["user_id"]}, {"_id": 1}
    ):
        confirms += 1
    return {
        **srv.serialize_user(u),
        "reports_count": total_reports,
        "confirmations_count": confirms,
        "history": history,
        "history_total": history_total,
        "history_offset": offset,
        "history_limit": limit,
    }


@router.post("/profile/avatar")
async def upload_avatar(body: "srv.AvatarIn", request: Request):
    """Accept a base64 image, compress + resize to 256x256, store as data URI."""
    u = await srv.current_user(request)
    raw = body.image
    if "," in raw and raw.lstrip().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw)
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Image invalide")
    # Square crop centered, then resize to 256.
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop(
        (left, top, left + side, top + side)
    ).resize((256, 256), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82, optimize=True)
    encoded = base64.b64encode(buf.getvalue()).decode()
    picture = f"data:image/jpeg;base64,{encoded}"
    await srv.db.users.update_one(
        {"user_id": u["user_id"]}, {"$set": {"picture": picture}}
    )
    fresh = await srv.db.users.find_one(
        {"user_id": u["user_id"]}, {"_id": 0}
    )
    return srv.serialize_user(fresh)


@router.post("/profile/location")
async def update_location(body: "srv.LocationIn", request: Request):
    """Save the caller's last known GPS so the server can target proximity pushes.

    Writes BOTH the legacy scalar pair (``last_lat``/``last_lng``) — kept for
    backward compat with older read paths — AND the GeoJSON ``last_loc``
    point that the new ``2dsphere`` index requires (P0 geo fan-out).
    """
    u = await srv.current_user(request)
    await srv.db.users.update_one(
        {"user_id": u["user_id"]},
        {"$set": {
            "last_lat": body.lat,
            "last_lng": body.lng,
            "last_loc_at": srv.now_utc(),
            # GeoJSON Point — order is [lng, lat] per RFC 7946 / MongoDB spec.
            "last_loc": {
                "type": "Point",
                "coordinates": [float(body.lng), float(body.lat)],
            },
        }},
    )
    return {"ok": True}


@router.put("/profile/preferences")
async def update_preferences(body: "srv.PreferencesIn", request: Request):
    """Update notify_radius_km and/or muted_types."""
    u = await srv.current_user(request)
    update: dict = {}
    if body.notify_radius_km is not None:
        update["notify_radius_km"] = float(body.notify_radius_km)
    if body.muted_types is not None:
        update["muted_types"] = [
            t for t in body.muted_types if t in srv.REPORT_TYPES
        ]
    if body.zoom_btn_pos is not None:
        try:
            update["zoom_btn_pos"] = {
                "x": float(body.zoom_btn_pos.get("x", 0)),
                "y": float(body.zoom_btn_pos.get("y", 0)),
            }
        except (TypeError, ValueError, AttributeError):
            pass
    if update:
        await srv.db.users.update_one(
            {"user_id": u["user_id"]}, {"$set": update}
        )
    fresh = await srv.db.users.find_one(
        {"user_id": u["user_id"]}, {"_id": 0}
    )
    return srv.serialize_user(fresh)


# ─── V1.2 — Phase 2 gamification endpoints ────────────────────────────────
@router.post("/profile/ping-open")
async def ping_open(request: Request):
    """Called once per app open (foreground). Handles three concerns:

    1. Award +1 grade point once per UTC calendar day.
    2. Bonus +4 when the user hits a 3-day consecutive streak (that same day).
    3. Apply the -1 inactivity penalty when returning after ≥30 days.

    Returns a summary the client can render as a friendly toast::

        {"awarded": int, "reason": str, "streak": int, "user": {...}}
    """
    u = await srv.current_user(request)
    uid = u["user_id"]
    today = PT.utc_day_key()
    last_day: Optional[str] = u.get("last_open_day")
    prev_streak = int(u.get("open_streak") or 0)

    awarded = 0
    reason = ""
    new_streak = prev_streak

    if last_day == today:
        # Already counted today — no-op, but still return the current streak.
        pass
    else:
        # Inactivity check first — user was gone for > 30 UTC days.
        if last_day and PT.days_between(last_day, today) > 30:
            await PT.award_points(
                srv.db, uid, PT.POINTS_INACTIVITY_30D, PT.REASON_INACTIVITY,
            )
        # Compute streak: consecutive iff last_day was exactly yesterday.
        if last_day and PT.days_between(last_day, today) == 1:
            new_streak = prev_streak + 1
        else:
            new_streak = 1

        # Base +1.
        await PT.award_points(srv.db, uid, PT.POINTS_OPEN_APP, PT.REASON_OPEN_APP)
        awarded += PT.POINTS_OPEN_APP
        reason = PT.REASON_OPEN_APP

        # Streak bonus (only on day 3 exactly, per PO spec).
        if new_streak == 3:
            await PT.award_points(
                srv.db, uid, PT.POINTS_STREAK_3_BONUS, PT.REASON_STREAK_3,
            )
            awarded += PT.POINTS_STREAK_3_BONUS
            reason = PT.REASON_STREAK_3

        await srv.db.users.update_one(
            {"user_id": uid},
            {"$set": {"last_open_day": today, "open_streak": new_streak}},
        )

    fresh = await srv.db.users.find_one({"user_id": uid}, {"_id": 0})
    return {
        "awarded": awarded,
        "reason": reason,
        "streak": new_streak,
        "user": srv.serialize_user(fresh),
    }


@router.get("/profile/points-history")
async def points_history(request: Request, limit: int = 10):
    """Return the caller's last N (default 10, capped at 50) history events.

    Each row: ``{ts, delta_points, delta_reliability, reason, report_id}``.
    """
    u = await srv.current_user(request)
    try:
        limit = max(1, min(int(limit), 200))
    except Exception:
        limit = 10
    rows: list[dict] = []
    cursor = (
        srv.db.points_history
        .find({"user_id": u["user_id"]}, {"_id": 0})
        .sort("ts", -1)
        .limit(limit)
    )
    async for r in cursor:
        rows.append({
            "ts": r.get("ts"),
            "delta_points": int(r.get("delta_points") or 0),
            "delta_reliability": int(r.get("delta_reliability") or 0),
            "reason": r.get("reason") or "",
            "report_id": r.get("report_id"),
        })
    return {"items": rows, "limit": limit}


# ─── Phase 3a — Referral & Friends ────────────────────────────────────────
@router.get("/profile/referral")
async def get_referral(request: Request):
    """Return the caller's referral code plus a share-ready link/text."""
    u = await srv.current_user(request)
    code = await REF.ensure_referral_code(srv.db, u["user_id"])
    # Count friends already onboarded via my code.
    friends_count = 0
    active_count = 0
    if code:
        friends_count = await srv.db.users.count_documents({"referred_by": code})
        active_count = await srv.db.users.count_documents({
            "referred_by": code,
            "referral_bonus_paid": True,
        })
    join_url = f"https://signalmar.app/join?ref={code}" if code else ""
    return {
        "referral_code": code,
        "join_url": join_url,
        "friends_count": friends_count,
        "active_count": active_count,
        "bonus_per_active_friend": REF.POINTS_REFERRAL_BONUS,
    }


def _friend_row(u: dict) -> dict:
    """Compact projection returned by the /friends list endpoint."""
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


@router.get("/profile/friends")
async def get_friends(request: Request):
    """List the users invited by the caller (referred_by == my referral_code)."""
    u = await srv.current_user(request)
    friends = await REF.list_friends(srv.db, u["user_id"])
    return {"items": [_friend_row(f) for f in friends]}


@router.get("/profile/friends/{friend_id}")
async def get_friend_detail(friend_id: str, request: Request):
    """Return the friend's public profile + 3 last reports + 3 last confirmations.

    V3b guard: the target must be in the caller's ``friends`` array (any of
    the two ways a friendship can be created — referral link at signup OR an
    in-app friend request accepted). This replaces the legacy referral-only
    check that unfairly locked out mutual friends.
    """
    u = await srv.current_user(request)
    friend = await srv.db.users.find_one({"user_id": friend_id}, {"_id": 0})
    if not friend:
        raise HTTPException(status_code=404, detail="Ami introuvable")
    me = await srv.db.users.find_one(
        {"user_id": u["user_id"]}, {"_id": 0, "friends": 1, "referral_code": 1},
    )
    is_friend = friend_id in ((me or {}).get("friends") or [])
    # Backwards-compat: also honour legacy referral links so users onboarded
    # before Phase 3b keep seeing their filleuls.
    referred_here = (
        (me or {}).get("referral_code")
        and friend.get("referred_by") == (me or {}).get("referral_code")
    )
    if not is_friend and not referred_here:
        raise HTTPException(
            status_code=403,
            detail="Cet utilisateur n'est pas dans votre liste d'amis.",
        )

    # 3 last reports authored by the friend.
    last_reports_cursor = (
        srv.db.reports
        .find({"author_id": friend_id}, {"_id": 0})
        .sort("created_at", -1)
        .limit(3)
    )
    last_reports = [srv.serialize_report(r, u["user_id"]) async for r in last_reports_cursor]

    # 3 last confirmations made by the friend (they appear in `confirmations`
    # list of some reports).
    last_confirms_cursor = (
        srv.db.reports
        .find({"confirmations": friend_id}, {"_id": 0})
        .sort("last_confirmed_at", -1)
        .limit(3)
    )
    last_confirms = [srv.serialize_report(r, u["user_id"]) async for r in last_confirms_cursor]

    return {
        "friend": _friend_row(friend),
        "last_reports": last_reports,
        "last_confirmations": last_confirms,
    }




# ── Phase B — Subscription & viral referral rewards ─────────────────────
@router.get("/profile/subscription")
async def profile_subscription(request: Request):
    """Snapshot of the caller's Premium subscription + referral progress.
    Combines the subscription state (bonus months, premium_until) with the
    ordered list of referrals (referee display, current status, months
    awarded). Consumed by the new « Abonnement » screen."""
    from core import subscription as SUB
    u = await srv.current_user(request)
    state = await SUB.get_subscription_state(srv.db, u["user_id"])
    referrals = await SUB.list_my_referrals(srv.db, u["user_id"])
    return {"subscription": state, "referrals": referrals}
