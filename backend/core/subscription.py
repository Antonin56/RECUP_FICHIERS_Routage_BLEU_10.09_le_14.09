"""Phase B — Subscription bonus tracking (viral referral rewards).

Business rules (locked with the founder on 08/07/2026):

* One-tier referral only (no MLM).
* A referral is worth **1 month of Premium** to the referrer, awarded only
  when the referee has:
    1. Signed up with the referrer's code attached.
    2. Created a first signalement.
    3. Received at least one confirmation from an *external* member —
       "external" meaning **not in a common private group** with the
       referee. This filters out same-club / same-crew ring farming.
* Caps: **max 10 pending** referrals simultaneously per referrer, **max
  12 confirmed months** cumulated (any extra referrals still consume the
  pending slot but no additional month is credited beyond 12).
* Each referee can trigger at most one bonus (linked to their first
  confirmed report only, idempotent via the ``months_awarded`` flag on
  the referrals doc).

Storage layout
--------------
* ``referrals`` collection (source of truth):
    { referral_id, referrer_user_id, referee_user_id, code_used,
      linked_at, first_report_id, first_report_at, confirmed_at,
      status ∈ {pending_report, pending_confirmation, confirmed,
                rejected_farm, expired},
      months_awarded (0|1) }

* ``users`` doc gains three top-level fields (denormalised for fast
  profile reads):
    - ``subscription_bonus_months_confirmed`` (int, cumulative)
    - ``subscription_bonus_months_pending``  (int, live count of open
      referrals — recomputed at write time)
    - ``subscription_premium_until``         (unix ts, base_date + N months)

The pending count is *also* recomputable on demand from the collection —
we store it to avoid a group-by on every profile hit.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("signalmar.subscription")

MAX_PENDING_REFERRALS = 10
MONTH_SECONDS = 30 * 24 * 3600  # calendar-safe enough for premium computation
# Règles 10/07/2026 (écrasent celles du 08/07) :
#   * Premium OFFERT à 100 % pendant 1 an pour chaque compte (dérivé de
#     created_at — aucun champ à migrer).
#   * Un filleul actif = +20 pts (core.referral.pay_referral_bonus).
#   * Chaque palier de 100 pts gagnés (à partir du 10/07/2026, baseline
#     par utilisateur) = +1 mois Premium automatique (core.points).
#   * Aucune tacite reconduction — renouvellement manuel uniquement.
FREE_YEAR_SECONDS = 365 * 24 * 3600
POINTS_PER_PREMIUM_MONTH = 100


# ── Helpers ────────────────────────────────────────────────────────────
async def _referee_group_ids(db, referee_uid: str) -> set[str]:
    return {
        m["group_id"] async for m in db.group_members.find(
            {"user_id": referee_uid}, {"_id": 0, "group_id": 1},
        )
    }


async def _is_external_confirmer(
    db, confirmer_uid: str, referee_uid: str,
) -> bool:
    """The confirmer counts as 'external' when they do NOT share any
    private group with the referee. This is the anti-farm barrier
    against same-club auto-confirmations. Additional heuristics
    (phone-contact overlap, IP proximity) can be layered later; the
    group check alone already stops the most obvious ring farming."""
    if not confirmer_uid or not referee_uid or confirmer_uid == referee_uid:
        return False
    referee_groups = await _referee_group_ids(db, referee_uid)
    if not referee_groups:
        return True  # referee is in no group → anyone external is external
    shared = await db.group_members.find_one(
        {"user_id": confirmer_uid, "group_id": {"$in": list(referee_groups)}},
        {"_id": 0},
    )
    return not bool(shared)


async def _recount_pending(db, referrer_uid: str) -> int:
    n = await db.referrals.count_documents({
        "referrer_user_id": referrer_uid,
        "status": {"$in": ["pending_report", "pending_confirmation"]},
    })
    await db.users.update_one(
        {"user_id": referrer_uid},
        {"$set": {"subscription_bonus_months_pending": int(n)}},
    )
    return n


def _bump_premium_until(current: Optional[int], months: int) -> int:
    """Add ``months`` calendar months (30-day steps) to the user's
    current premium_valid_until, starting from `max(now, current)` so a
    lapsed subscription resumes at "now" rather than in the past."""
    now = int(time.time())
    base = max(current or 0, now)
    return base + months * MONTH_SECONDS


# ── Public API ────────────────────────────────────────────────────────
async def create_pending_referral(
    db, referrer_uid: str, referee_uid: str, code_used: str,
) -> Optional[str]:
    """Called at signup once the referrer link is validated. Enforces
    the MAX_PENDING cap: if the referrer is already at 10 pending,
    the referral is created with status=``rejected_farm`` so we keep
    the audit trail but no month can ever be credited."""
    if not referrer_uid or not referee_uid or referrer_uid == referee_uid:
        return None
    # Cap check before insert — this is the antifraud gate.
    pending = await db.referrals.count_documents({
        "referrer_user_id": referrer_uid,
        "status": {"$in": ["pending_report", "pending_confirmation"]},
    })
    status = (
        "pending_report" if pending < MAX_PENDING_REFERRALS
        else "rejected_farm"
    )
    referral_id = "rf_" + uuid.uuid4().hex[:12]
    now = int(time.time())
    await db.referrals.insert_one({
        "referral_id": referral_id,
        "referrer_user_id": referrer_uid,
        "referee_user_id": referee_uid,
        "code_used": code_used or "",
        "linked_at": now,
        "first_report_id": None,
        "first_report_at": None,
        "confirmed_at": None,
        "status": status,
        "months_awarded": 0,
    })
    await _recount_pending(db, referrer_uid)
    logger.info("referral %s → %s (%s) status=%s",
                referrer_uid, referee_uid, code_used, status)
    return referral_id


async def on_first_report(db, referee_uid: str, report_id: str) -> None:
    """Mark the referral as awaiting confirmation as soon as the referee
    posts their first signalement. Idempotent: only the *first* report
    counts; subsequent reports don't move the state further."""
    if not referee_uid or not report_id:
        return
    res = await db.referrals.update_one(
        {
            "referee_user_id": referee_uid,
            "status": "pending_report",
            "first_report_id": None,
        },
        {
            "$set": {
                "first_report_id": report_id,
                "first_report_at": int(time.time()),
                "status": "pending_confirmation",
            },
        },
    )
    if res.modified_count:
        # We just moved from pending_report → pending_confirmation — the
        # pending count itself doesn't change, but we refresh anyway to
        # heal any drift on legacy accounts.
        row = await db.referrals.find_one(
            {"referee_user_id": referee_uid,
             "status": "pending_confirmation"},
            {"_id": 0, "referrer_user_id": 1},
        )
        if row:
            await _recount_pending(db, row["referrer_user_id"])


async def try_award_bonus(
    db,
    *,
    report_id: str,
    report_author_uid: str,
    confirmer_uid: str,
) -> Optional[dict]:
    """Called from the confirmation flow. Awards **one month of premium
    bonus** to the referrer iff:
      • The report is the referee's first (matches referrals.first_report_id).
      • The confirmer is external (see ``_is_external_confirmer``).
      • The referrer hasn't hit the 12-month cap.
    Returns a dict describing the payout or None if nothing was awarded.
    Idempotent via ``months_awarded`` flag on the referral doc."""
    if not report_id or not report_author_uid or not confirmer_uid:
        return None
    ref = await db.referrals.find_one({
        "referee_user_id": report_author_uid,
        "first_report_id": report_id,
        "status": "pending_confirmation",
        "months_awarded": 0,
    }, {"_id": 0})
    if not ref:
        return None
    if not await _is_external_confirmer(db, confirmer_uid, report_author_uid):
        return None  # keep referral in pending_confirmation, wait for another
    referrer_uid = ref["referrer_user_id"]

    # Règle 10/07/2026 — le mois direct est REMPLACÉ par +20 pts (crédités
    # par core.referral.pay_referral_bonus dans le flux de confirmation) ;
    # les mois Premium arrivent désormais via les paliers de 100 pts
    # (core.points.check_point_months). On marque simplement le parrainage
    # « confirmed » pour l'UI et l'audit.
    now = int(time.time())
    await db.referrals.update_one(
        {"referral_id": ref["referral_id"]},
        {"$set": {
            "status": "confirmed",
            "confirmed_at": now,
            "months_awarded": 0,
            "external_confirmer_uid": confirmer_uid,
        }},
    )
    await _recount_pending(db, referrer_uid)
    logger.info(
        "referral confirmed: referrer=%s referee=%s (récompense: +20 pts via referral.py)",
        referrer_uid, report_author_uid,
    )
    return {
        "referrer_user_id": referrer_uid,
        "referee_user_id": report_author_uid,
        "months_awarded": 0,
    }


async def list_my_referrals(db, referrer_uid: str) -> list[dict]:
    """Return the referrer's referrals, freshest first, with denormalised
    referee display info for the UI."""
    if not referrer_uid:
        return []
    docs = [
        d async for d in db.referrals.find(
            {"referrer_user_id": referrer_uid},
            {"_id": 0},
        ).sort("linked_at", -1)
    ]
    if not docs:
        return []
    refee_ids = [d["referee_user_id"] for d in docs]
    users_by = {
        u["user_id"]: u async for u in db.users.find(
            {"user_id": {"$in": refee_ids}},
            {"_id": 0, "user_id": 1, "pseudo": 1, "name": 1, "picture": 1,
             "created_at": 1},
        )
    }
    out = []
    for d in docs:
        u = users_by.get(d["referee_user_id"], {})
        out.append({
            "referral_id": d["referral_id"],
            "status": d["status"],
            "months_awarded": int(d.get("months_awarded") or 0),
            "linked_at": d.get("linked_at"),
            "first_report_at": d.get("first_report_at"),
            "confirmed_at": d.get("confirmed_at"),
            "referee": {
                "user_id": d["referee_user_id"],
                "pseudo": u.get("pseudo") or u.get("name") or "Marin",
                "picture": u.get("picture") or "",
            },
        })
    return out


def _created_at_ts(created_at) -> Optional[int]:
    """created_at peut être un datetime (srv.now_utc) ou un timestamp."""
    if created_at is None:
        return None
    if isinstance(created_at, (int, float)):
        return int(created_at)
    try:
        return int(created_at.timestamp())
    except Exception:
        return None


async def get_subscription_state(db, user_id: str) -> dict:
    """Snapshot of the user's Premium subscription for the profile UI."""
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
    confirmed = int(u.get("subscription_bonus_months_confirmed") or 0)
    pending = int(u.get("subscription_bonus_months_pending") or 0)
    now = int(time.time())

    # Année Premium offerte (dérivée de created_at, aucun champ stocké).
    created_ts = _created_at_ts(u.get("created_at"))
    free_until = (created_ts + FREE_YEAR_SECONDS) if created_ts else None

    # Mois gagnés (paliers de points, anciens bonus…) stockés dans
    # subscription_premium_until ; le Premium effectif = le plus lointain.
    earned_until = u.get("subscription_premium_until")
    premium_until = max(
        [t for t in (free_until, earned_until) if t], default=None,
    )
    is_premium = bool(premium_until and premium_until > now)
    remaining_days = (
        int((premium_until - now) / 86400) if is_premium else 0
    )

    # Progression points → mois (règle 10/07/2026, baseline non rétroactive).
    points = int(u.get("points") or 0)
    baseline = int(u.get("points_premium_baseline") or 0)
    months_awarded = int(u.get("points_months_awarded") or 0)
    earned_pts = max(0, points - baseline)
    progress = earned_pts % POINTS_PER_PREMIUM_MONTH

    return {
        "bonus_months_confirmed": confirmed,
        "bonus_months_pending": pending,
        "cap_pending": MAX_PENDING_REFERRALS,
        "premium_valid_until": premium_until,
        "premium_valid_until_iso": (
            datetime.utcfromtimestamp(premium_until).isoformat() + "Z"
            if premium_until else None
        ),
        "is_premium": is_premium,
        "remaining_days": remaining_days,
        "registered_at": u.get("created_at"),
        # Premium offert 1ʳᵉ année :
        "free_year_until": free_until,
        "free_year_active": bool(free_until and free_until > now),
        # Points → mois Premium :
        "points_per_month": POINTS_PER_PREMIUM_MONTH,
        "points_progress": progress,
        "points_to_next_month": POINTS_PER_PREMIUM_MONTH - progress,
        "points_months_awarded": months_awarded,
    }


async def ensure_indexes(db) -> None:
    await db.referrals.create_index("referral_id", unique=True)
    await db.referrals.create_index("referrer_user_id")
    await db.referrals.create_index("referee_user_id")
    await db.referrals.create_index([
        ("referrer_user_id", 1), ("status", 1),
    ])
    await db.referrals.create_index([
        ("referee_user_id", 1), ("status", 1),
    ])


# Silence unused-import warning without hiding the intent:
_ = Any
