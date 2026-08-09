"""Phase 3c — In-app notifications persistence + geo-indexed fan-out (P0).

Design:
    * Every push we fire is also persisted here so the recipient can see it
      later, even when they were offline or hadn't built with Firebase yet.
    * Kept simple on purpose: no fan-out, no channels, no priorities — just a
      per-user timeline the client can render in a bell-icon drawer.

Scaling notes (500 k users target):
    * ``dispatch_proximity_push`` REPLACES the previous synchronous
      ``users.find({...})`` full-scan. It uses a ``2dsphere`` index on
      ``users.last_loc`` + ``$geoWithin/$centerSphere`` so MongoDB only
      returns the ~O(√N) candidates inside the widest possible radius
      (500 km, hard cap of the per-user notify_radius_km).
    * The per-user radius / muted-types filter is applied AFTER the
      geo-query on a very small candidate set — cheap enough to keep here.
    * Callers should invoke ``dispatch_proximity_push`` via FastAPI
      ``BackgroundTasks`` so report creation returns immediately.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

logger = logging.getLogger("signalmar.notifications")

# Earth mean radius in kilometres — matches MongoDB's $centerSphere convention.
_EARTH_KM = 6378.1
# Hard cap on the per-user notify_radius_km (also used by preferences).
_MAX_RADIUS_KM = 500.0
_MIN_RADIUS_KM = 0.5
# GPS-fix freshness cutoff — users who haven't checked in for more than this
# window are excluded from proximity dispatch (they're likely offline).
_LOC_FRESHNESS_HOURS = 24


NOTIF_LIMIT_DEFAULT = 30
NOTIF_LIMIT_MAX = 100


async def create(
    db,
    user_id: Optional[str],
    *,
    kind: str,
    title: str,
    message: str,
    action_url: Optional[str] = None,
    payload: Optional[dict] = None,
    dedup_key: Optional[str] = None,
) -> Optional[dict]:
    """Persist a single notification row (best-effort).

    ``dedup_key`` mirrors the push idempotency key so the same event never
    lands in the drawer twice (e.g. duplicate confirm click).
    """
    if not user_id:
        return None
    if dedup_key:
        try:
            existing = await db.notifications.find_one(
                {"user_id": user_id, "dedup_key": dedup_key},
                {"_id": 0, "id": 1},
            )
            if existing:
                return None
        except Exception as e:
            logger.warning("dedup lookup failed: %s", e)
    doc = {
        "id": uuid.uuid4().hex,
        "user_id": user_id,
        "kind": kind,
        "title": title,
        "message": message,
        "action_url": action_url,
        "payload": payload or {},
        "dedup_key": dedup_key,
        "created_at": datetime.now(timezone.utc),
        "read_at": None,
    }
    try:
        await db.notifications.insert_one(doc)
    except Exception as e:
        logger.warning("notif insert failed for %s: %s", user_id, e)
        return None
    # Trim to a reasonable per-user cap — no one needs 5000 notifs.
    try:
        count = await db.notifications.count_documents({"user_id": user_id})
        if count > 500:
            oldest = await db.notifications.find(
                {"user_id": user_id}, {"_id": 0, "id": 1, "created_at": 1},
            ).sort("created_at", 1).limit(count - 500).to_list(None)
            ids = [o["id"] for o in oldest]
            if ids:
                await db.notifications.delete_many({"id": {"$in": ids}})
    except Exception:
        pass
    doc.pop("_id", None)
    return doc


async def notify_and_push(
    db,
    user_id: str,
    send_push_fn,
    *,
    kind: str,
    title: str,
    message: str,
    action_url: Optional[str] = None,
    payload: Optional[dict] = None,
    idempotency_key: Optional[str] = None,
) -> None:
    """Combined helper: persist + push (never raises).

    ``send_push_fn`` is passed by the caller (typically ``srv.send_push``) so
    this module stays free of server-side circular imports.
    """
    await create(
        db, user_id,
        kind=kind, title=title, message=message, action_url=action_url,
        payload=payload, dedup_key=idempotency_key,
    )
    try:
        await send_push_fn(
            recipients=[user_id],
            data={
                "title": title,
                "message": message,
                "action_url": action_url or "",
            },
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        logger.warning("push failed for %s: %s", user_id, e)


async def unread_count(db, user_id: str) -> int:
    if not user_id:
        return 0
    try:
        return await db.notifications.count_documents({
            "user_id": user_id, "read_at": None,
        })
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# P0 — Geo-indexed proximity fan-out
# ---------------------------------------------------------------------------
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Duplicated here to keep this module free
    of a hard dependency on server.py (avoids circular imports)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * _EARTH_KM * math.asin(math.sqrt(a))


async def find_nearby_recipients(
    db,
    *,
    lat: float,
    lng: float,
    exclude_user_id: Optional[str] = None,
    report_type: Optional[str] = None,
    max_km: float = _MAX_RADIUS_KM,
) -> list[str]:
    """Return the ordered list of user_ids whose last known position is
    inside their own preferred ``notify_radius_km`` around (lat, lng).

    Fast path (500 k users):
        * MongoDB ``$geoWithin`` on the ``2dsphere`` index over ``users.last_loc``
          returns only the (few thousand) users physically inside the widest
          possible radius (``max_km``).
        * Freshness gate (last_loc_at ≥ now-24h) is applied in the query.
        * Per-user personal radius + muted-types filter is applied in Python
          on that small candidate set (still O(k) where k << N).

    Falls back to the legacy full-scan when the geo query fails (e.g. index
    not yet created, tests) so the feature never dead-ends the caller.
    """
    max_km = min(_MAX_RADIUS_KM, max(_MIN_RADIUS_KM, float(max_km)))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_LOC_FRESHNESS_HOURS)
    radius_rad = max_km / _EARTH_KM

    query: dict = {
        "last_loc": {
            "$geoWithin": {"$centerSphere": [[lng, lat], radius_rad]}
        },
        "last_loc_at": {"$gte": cutoff},
    }
    if exclude_user_id:
        query["user_id"] = {"$ne": exclude_user_id}

    projection = {
        "_id": 0, "user_id": 1, "last_lat": 1, "last_lng": 1,
        "notify_radius_km": 1, "muted_types": 1,
    }

    recipients: list[str] = []
    try:
        cursor = db.users.find(query, projection)
    except Exception as e:
        logger.warning("geo query failed, falling back to legacy scan: %s", e)
        # Legacy fallback — small deployments / test fixtures without the
        # 2dsphere index yet.
        cursor = db.users.find(
            {
                "last_lat": {"$exists": True},
                "last_lng": {"$exists": True},
                "last_loc_at": {"$gte": cutoff},
                **({"user_id": {"$ne": exclude_user_id}} if exclude_user_id else {}),
            },
            projection,
        )

    async for nu in cursor:
        if report_type and report_type in (nu.get("muted_types") or []):
            continue
        r_km = min(
            _MAX_RADIUS_KM,
            max(_MIN_RADIUS_KM, float(nu.get("notify_radius_km") or 15.0)),
        )
        lat2 = nu.get("last_lat")
        lng2 = nu.get("last_lng")
        if lat2 is None or lng2 is None:
            continue
        if _haversine_km(lat, lng, float(lat2), float(lng2)) <= r_km:
            recipients.append(nu["user_id"])
    return recipients


async def dispatch_proximity_push(
    db,
    send_push_fn: Callable,
    *,
    lat: float,
    lng: float,
    exclude_user_id: Optional[str],
    report_type: Optional[str],
    title: str,
    message: str,
    action_url: str,
    idempotency_key: str,
    max_km: float = _MAX_RADIUS_KM,
    chunk_size: int = 100,
) -> int:
    """Full proximity fan-out: geo-filter → chunked push. Safe for
    BackgroundTasks (never raises). Returns the number of recipients."""
    try:
        recipients = await find_nearby_recipients(
            db,
            lat=lat, lng=lng,
            exclude_user_id=exclude_user_id,
            report_type=report_type,
            max_km=max_km,
        )
    except Exception as e:
        logger.warning("proximity dispatch (find) failed: %s", e)
        return 0
    if not recipients:
        return 0
    # The Emergent push relay caps recipients per call at 100 (see send_push).
    # We chunk explicitly here so a single hot spot with 10k boaters doesn't
    # silently drop everyone past the 100th.
    for i in range(0, len(recipients), chunk_size):
        batch = recipients[i:i + chunk_size]
        try:
            await send_push_fn(
                recipients=batch,
                data={
                    "title": title, "message": message,
                    "action_url": action_url,
                },
                idempotency_key=idempotency_key,
            )
        except Exception as e:
            logger.warning(
                "proximity push chunk %d failed: %s",
                i // chunk_size, e,
            )
    return len(recipients)


async def ensure_geo_indexes(db) -> None:
    """Create the ``2dsphere`` index on ``users.last_loc`` (idempotent).

    Also backfills ``last_loc`` from the legacy ``last_lat``/``last_lng``
    pair for existing users so the new index is immediately useful without
    a manual migration.
    """
    try:
        await db.users.create_index([("last_loc", "2dsphere")], sparse=True)
    except Exception as e:
        logger.warning("2dsphere index create failed: %s", e)
    # Backfill — one-shot, safe to run on every boot (matches only docs that
    # still lack the geo field).
    try:
        cursor = db.users.find(
            {
                "last_lat": {"$exists": True},
                "last_lng": {"$exists": True},
                "last_loc": {"$exists": False},
            },
            {"_id": 0, "user_id": 1, "last_lat": 1, "last_lng": 1},
        )
        n = 0
        async for u in cursor:
            try:
                await db.users.update_one(
                    {"user_id": u["user_id"]},
                    {"$set": {
                        "last_loc": {
                            "type": "Point",
                            "coordinates": [
                                float(u["last_lng"]),
                                float(u["last_lat"]),
                            ],
                        },
                    }},
                )
                n += 1
            except Exception:
                continue
        if n:
            logger.info("last_loc backfill: %d users", n)
    except Exception as e:
        logger.warning("last_loc backfill failed: %s", e)
