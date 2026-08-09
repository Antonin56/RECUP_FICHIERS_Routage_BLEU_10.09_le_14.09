"""Phase 2 V1.2 — Points & Fiabilité rules.

Central module holding every gain/loss rule for the Marine Nationale grade
progression and the 0-100 % Indice de fiabilité. Values were validated by the
product owner on 2026-07-06.

Design:
    * ``award_points`` and ``award_reliability`` are the only entry-points.
    * Both write the delta to the ``points_history`` collection so the profile
      screen can show a live journal of the last events.
    * Both are best-effort (log-and-continue on Mongo failure).

Constants:
    POINTS_*      → grade delta (int)
    RELIABILITY_* → % delta (int, applied to the 0-100 reliability_pct field)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("signalmar.points")


# ─── GRADE POINTS ──────────────────────────────────────────────────────────
POINTS_OPEN_APP           = 1     # per 24h calendar day
POINTS_STREAK_3_BONUS     = 4     # BONUS added on top of the daily +1 on day 3
POINTS_FIRST_REPORT       = 10    # once in a lifetime (first_report_bonus_given)
POINTS_REPORT             = 5     # every subsequent report
POINTS_CONFIRM_OTHER      = 2     # per confirmation of somebody else's report
POINTS_INACTIVITY_30D     = -1    # applied when returning after 30d silence
POINTS_FALSE_REPORT       = -10   # own report flagged false by community
POINTS_MODERATED          = -30   # comment or image moderated
POINTS_WARNING            = -100  # 3rd moderation event in 30 days = warning

# ─── RELIABILITY (0-100 %) ────────────────────────────────────────────────
RELIABILITY_DEFAULT       = 50    # everyone starts at neutral 50 %
RELIABILITY_MIN           = 0
RELIABILITY_MAX           = 100
RELIABILITY_CONFIRM_OTHER = 3     # my report confirmed by another user
RELIABILITY_INFIRM_LT1H   = -2    # per user infirming, within 1h of creation
RELIABILITY_FALSE         = -10   # ≥2 different infirmers within 1h → flagged

# ─── ANTI-ABUSE ───────────────────────────────────────────────────────────
CONFIRM_CAP_PER_DAY       = 10    # max confirmations rewarded / user / day
INFIRM_WINDOW_MIN         = 60    # "moins de 1h" window for infirmations
MODERATION_WARNING_WINDOW = 30    # days rolling window for the -100 warning
MODERATION_WARNING_COUNT  = 3     # nth moderation event = warning


# ─── HISTORY REASONS ──────────────────────────────────────────────────────
# Kept as short i18n-friendly labels (French) rendered as-is on the profile.
REASON_OPEN_APP      = "Ouverture de l'app"
REASON_STREAK_3      = "3 jours de suite"
REASON_FIRST_REPORT  = "1er signalement"
REASON_REPORT        = "Nouveau signalement"
REASON_CONFIRM       = "Confirmation d'un signalement"
REASON_CONFIRM_AUTHOR= "Votre signalement a été confirmé"
REASON_INACTIVITY    = "Inactivité 30 jours"
REASON_INFIRM        = "Votre signalement a été infirmé"
REASON_FALSE         = "Votre signalement déclaré faux"
REASON_MODERATED     = "Contenu modéré"
REASON_WARNING       = "Avertissement modération"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _record_history(
    db,
    user_id: str,
    delta_points: int,
    delta_reliability: int,
    reason: str,
    report_id: Optional[str] = None,
) -> None:
    """Append one event to the points_history collection (best-effort)."""
    try:
        await db.points_history.insert_one({
            "user_id": user_id,
            "ts": _now_utc(),
            "delta_points": int(delta_points),
            "delta_reliability": int(delta_reliability),
            "reason": reason,
            "report_id": report_id,
        })
    except Exception as e:
        logger.warning("points_history insert failed for %s: %s", user_id, e)


async def check_point_months(db, user_id: Optional[str]) -> None:
    """Règle 10/07/2026 — chaque palier de 100 points GAGNÉS (depuis la
    baseline propre à l'utilisateur, non rétroactif) débloque automatiquement
    +1 mois de Premium. Les mois débloqués sont définitifs même si les points
    redescendent ensuite. Best-effort (log-and-continue)."""
    if not user_id:
        return
    try:
        from core.subscription import (
            FREE_YEAR_SECONDS, MONTH_SECONDS, POINTS_PER_PREMIUM_MONTH,
            _created_at_ts,
        )
        u = await db.users.find_one(
            {"user_id": user_id},
            {"_id": 0, "points": 1, "points_premium_baseline": 1,
             "points_months_awarded": 1, "subscription_premium_until": 1,
             "created_at": 1},
        ) or {}
        points = int(u.get("points") or 0)
        baseline = int(u.get("points_premium_baseline") or 0)
        awarded = int(u.get("points_months_awarded") or 0)
        earned = max(0, points - baseline)
        target = earned // POINTS_PER_PREMIUM_MONTH
        if target <= awarded:
            return
        add = target - awarded
        # Les mois gagnés s'empilent APRÈS l'année offerte / le Premium en
        # cours (pas de chevauchement perdu).
        import time as _time
        now = int(_time.time())
        created_ts = _created_at_ts(u.get("created_at"))
        base = max(
            now,
            int(u.get("subscription_premium_until") or 0),
            (created_ts + FREE_YEAR_SECONDS) if created_ts else 0,
        )
        new_until = base + add * MONTH_SECONDS
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "points_months_awarded": target,
                "subscription_premium_until": new_until,
            }},
        )
        await _record_history(
            db, user_id, 0, 0,
            f"Palier {target * POINTS_PER_PREMIUM_MONTH} pts — +{add} mois Premium offert{'s' if add > 1 else ''} 🎁",
        )
        logger.info("point-months: %s +%d mois (target=%d)", user_id, add, target)
    except Exception as e:
        logger.warning("check_point_months failed for %s: %s", user_id, e)


async def award_points(
    db,
    user_id: Optional[str],
    delta: int,
    reason: str,
    report_id: Optional[str] = None,
) -> None:
    """Increment the user's grade points and log the event to history."""
    if not user_id or delta == 0:
        return
    try:
        await db.users.update_one(
            {"user_id": user_id},
            {"$inc": {"points": int(delta)}},
        )
    except Exception as e:
        logger.warning("award_points failed for %s: %s", user_id, e)
        return
    await _record_history(db, user_id, delta, 0, reason, report_id)
    if delta > 0:
        await check_point_months(db, user_id)


async def award_reliability(
    db,
    user_id: Optional[str],
    delta: int,
    reason: str,
    report_id: Optional[str] = None,
) -> None:
    """Adjust the user's reliability_pct (0-100 clamped) and log the event."""
    if not user_id or delta == 0:
        return
    try:
        # Read the full user doc so we can migrate legacy pos/neg accounts
        # seamlessly on their first event under the new system.
        u = await db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
        current = read_reliability(u)
        nxt = max(RELIABILITY_MIN, min(RELIABILITY_MAX, current + int(delta)))
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"reliability_pct": nxt}},
        )
    except Exception as e:
        logger.warning("award_reliability failed for %s: %s", user_id, e)
        return
    await _record_history(db, user_id, 0, delta, reason, report_id)


async def award_both(
    db,
    user_id: Optional[str],
    delta_points: int,
    delta_reliability: int,
    reason: str,
    report_id: Optional[str] = None,
) -> None:
    """Combined delta on both counters — logs a single history row."""
    if not user_id or (delta_points == 0 and delta_reliability == 0):
        return
    try:
        if delta_points != 0:
            await db.users.update_one(
                {"user_id": user_id},
                {"$inc": {"points": int(delta_points)}},
            )
        if delta_reliability != 0:
            u = await db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
            current = read_reliability(u)
            nxt = max(
                RELIABILITY_MIN,
                min(RELIABILITY_MAX, current + int(delta_reliability)),
            )
            await db.users.update_one(
                {"user_id": user_id},
                {"$set": {"reliability_pct": nxt}},
            )
    except Exception as e:
        logger.warning("award_both failed for %s: %s", user_id, e)
        return
    await _record_history(
        db, user_id, delta_points, delta_reliability, reason, report_id,
    )
    if delta_points > 0:
        await check_point_months(db, user_id)


def read_reliability(u: dict) -> int:
    """Return the current fiabilité score.

    Migration:
        * If ``reliability_pct`` is set → use it as-is (new source of truth).
        * Otherwise fall back to the legacy pos/neg formula so existing users
          still see a sensible value until they trigger any new event.
    """
    if "reliability_pct" in u:
        try:
            return max(RELIABILITY_MIN, min(RELIABILITY_MAX, int(u["reliability_pct"])))
        except Exception:
            pass
    # Legacy formula: 50 + (pos - neg)*2, clamped 0..100.
    pos = int(u.get("reliability_pos", 0))
    neg = int(u.get("reliability_neg", 0))
    raw = 50 + (pos - neg) * 2
    return max(RELIABILITY_MIN, min(RELIABILITY_MAX, raw))


# ─── DAILY / STREAK helpers ────────────────────────────────────────────────
def utc_day_key(when: Optional[datetime] = None) -> str:
    """Return the UTC calendar day as YYYY-MM-DD (used to compute streaks)."""
    when = when or _now_utc()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d")


def days_between(day_a: str, day_b: str) -> int:
    """Absolute difference in days between two YYYY-MM-DD strings."""
    try:
        da = datetime.strptime(day_a, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        db_ = datetime.strptime(day_b, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return abs((db_ - da).days)
    except Exception:
        return 0


async def can_reward_confirmation(db, user_id: str) -> bool:
    """Anti-abuse: enforce a soft daily cap on confirmation rewards.

    Returns True if the user is under CONFIRM_CAP_PER_DAY confirmations for
    today (UTC). The caller is responsible for actually recording the reward.
    """
    if not user_id:
        return False
    today = utc_day_key()
    try:
        u = await db.users.find_one(
            {"user_id": user_id},
            {"_id": 0, "confirm_reward_day": 1, "confirm_reward_count": 1},
        ) or {}
        day = u.get("confirm_reward_day")
        count = int(u.get("confirm_reward_count", 0))
        if day != today:
            # Reset counter for the new day.
            await db.users.update_one(
                {"user_id": user_id},
                {"$set": {"confirm_reward_day": today, "confirm_reward_count": 0}},
            )
            count = 0
        if count >= CONFIRM_CAP_PER_DAY:
            return False
        await db.users.update_one(
            {"user_id": user_id},
            {"$inc": {"confirm_reward_count": 1}},
        )
        return True
    except Exception as e:
        logger.warning("confirm cap check failed for %s: %s", user_id, e)
        # Fail-open to preserve UX (don't block the confirmation itself).
        return True


async def register_moderation_event(db, user_id: Optional[str]) -> bool:
    """Record a moderation event and return True if this is the N-th offence
    within the rolling window (i.e. a warning must be issued)."""
    if not user_id:
        return False
    now = _now_utc()
    window_start = now - timedelta(days=MODERATION_WARNING_WINDOW)
    try:
        u = await db.users.find_one(
            {"user_id": user_id},
            {"_id": 0, "moderation_events": 1},
        ) or {}
        raw = u.get("moderation_events") or []
        # Keep only recent events + append the new one.
        recent = []
        for entry in raw:
            try:
                ts = entry if isinstance(entry, datetime) else datetime.fromisoformat(str(entry))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= window_start:
                    recent.append(ts)
            except Exception:
                continue
        recent.append(now)
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"moderation_events": recent}},
        )
        return len(recent) >= MODERATION_WARNING_COUNT
    except Exception as e:
        logger.warning("moderation_events failed for %s: %s", user_id, e)
        return False
