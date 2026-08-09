"""Phase 3a — Referral & Friends system.

Design:
    * Every user gets a unique short ``referral_code`` (6 chars, uppercase
      letters + digits, generated lazily on first read).
    * At signup the client may pass ``referral_code`` in the request body. If
      it matches a valid user we store that user's code in ``referred_by`` on
      the new account. The friendship is 1:N (a referrer has many referrals,
      each referred user has at most one referrer).
    * The referrer earns ``POINTS_REFERRAL_BONUS`` (+20 grade) ONLY when their
      referral's *first* signalement has been confirmed by ≥1 other user.
      This is checked in the report confirmation flow (``pay_referral_bonus``)
      and is idempotent: the ``referral_bonus_paid`` flag on the referred user
      guarantees a one-shot payout.
"""
from __future__ import annotations

import logging
import random
import string
from typing import Optional

logger = logging.getLogger("signalmar.referral")


POINTS_REFERRAL_BONUS = 20
CODE_LENGTH = 6
CODE_ALPHABET = string.ascii_uppercase + string.digits
# Ambiguous glyphs stripped so codes are readable on paper (0/O, 1/I, 5/S).
CODE_ALPHABET = "".join(c for c in CODE_ALPHABET if c not in "0O1I5S")


REASON_REFERRAL_BONUS = "Filleul actif — signalement confirmé"


def _generate_code() -> str:
    """Return a random human-friendly referral code."""
    return "".join(random.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


async def ensure_referral_code(db, user_id: str) -> str:
    """Return the caller's referral code, creating one on first access.

    We generate lazily rather than at signup so legacy accounts are backfilled
    transparently the first time they open the Friends screen.
    """
    if not user_id:
        return ""
    for _ in range(6):
        try:
            u = await db.users.find_one(
                {"user_id": user_id},
                {"_id": 0, "referral_code": 1},
            )
            if u and u.get("referral_code"):
                return str(u["referral_code"])
            code = _generate_code()
            # Guarantee uniqueness — retry on collision.
            clash = await db.users.find_one(
                {"referral_code": code}, {"_id": 0, "user_id": 1},
            )
            if clash:
                continue
            await db.users.update_one(
                {"user_id": user_id},
                {"$set": {"referral_code": code}},
            )
            return code
        except Exception as e:
            logger.warning("ensure_referral_code failed for %s: %s", user_id, e)
            break
    return ""


async def resolve_referrer(db, code: Optional[str]) -> Optional[dict]:
    """Return the user document matching ``code`` (case-insensitive), or None."""
    if not code:
        return None
    return await db.users.find_one(
        {"referral_code": str(code).strip().upper()},
        {"_id": 0},
    )


async def attach_referrer(db, new_user_id: str, code: Optional[str]) -> bool:
    """Called at signup: persist the referrer's code on the fresh account.

    Returns True if a valid referrer was linked, False otherwise (invalid code
    or self-referral).
    """
    if not code or not new_user_id:
        return False
    ref = await resolve_referrer(db, code)
    if not ref or ref.get("user_id") == new_user_id:
        return False
    try:
        await db.users.update_one(
            {"user_id": new_user_id},
            {"$set": {
                "referred_by": ref["referral_code"],
                "referrer_user_id": ref["user_id"],
                "referral_bonus_paid": False,
            }},
        )
        return True
    except Exception as e:
        logger.warning("attach_referrer failed for %s: %s", new_user_id, e)
        return False


async def pay_referral_bonus(db, report_author_id: str, report_id: str) -> bool:
    """Award the +20 grade bonus to the referrer when a referred user's
    signalement is confirmed for the first time.

    Idempotent: the bonus is paid only once per referred account, based on the
    ``referral_bonus_paid`` flag on the referred user.
    """
    if not report_author_id:
        return False
    try:
        author = await db.users.find_one(
            {"user_id": report_author_id},
            {"_id": 0, "referred_by": 1, "referrer_user_id": 1, "referral_bonus_paid": 1},
        )
    except Exception as e:
        logger.warning("pay_referral_bonus fetch failed: %s", e)
        return False
    if not author:
        return False
    if author.get("referral_bonus_paid"):
        return False  # already paid — one-shot
    referrer_uid = author.get("referrer_user_id")
    if not referrer_uid:
        return False
    # Award, log history, mark author flag.
    from core import points as PT
    await PT.award_points(
        db, referrer_uid, POINTS_REFERRAL_BONUS,
        REASON_REFERRAL_BONUS, report_id=report_id,
    )
    try:
        await db.users.update_one(
            {"user_id": report_author_id},
            {"$set": {"referral_bonus_paid": True}},
        )
    except Exception as e:
        logger.warning("mark referral_bonus_paid failed: %s", e)
    return True


async def list_friends(db, user_id: str) -> list[dict]:
    """Return the friends invited by ``user_id`` (referred_by == my code)."""
    if not user_id:
        return []
    me = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "referral_code": 1},
    )
    my_code = (me or {}).get("referral_code")
    if not my_code:
        return []
    cursor = db.users.find(
        {"referred_by": my_code},
        {"_id": 0},
    ).sort("created_at", -1)
    return [row async for row in cursor]
