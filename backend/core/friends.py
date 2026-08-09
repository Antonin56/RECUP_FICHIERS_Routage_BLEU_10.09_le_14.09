"""Phase 3b — Friend requests & bidirectional friendships.

Design:
    * A friendship is stored as a symmetric ``friends: [user_id]`` array on
      each user document. Reads are O(1) per user, writes touch two docs on
      accept.
    * Pending requests live in the dedicated ``friend_requests`` collection
      so the /pending endpoint is a single indexed lookup per user.

Backwards-compat:
    * Users referred via a code (Phase 3a) are auto-added to both friend
      lists on signup, keeping the referral experience seamless.
    * The legacy ``list_friends`` in :mod:`core.referral` still walks the
      ``referred_by`` graph and is only used for the referral-count widget.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("signalmar.friends")

# ── E.164 normalisation ────────────────────────────────────────────────────
E164_RE = re.compile(r"^\+\d{8,15}$")


def normalize_phone(raw: Optional[str], default_cc: str = "+33") -> Optional[str]:
    """Return an E.164 phone number or None if not usable.

    Rules:
        * Strip whitespace, dashes, dots, parenthesis and non-digit chars
          (except a leading '+').
        * A leading '00' is converted to '+' (international dial-out).
        * A leading '0' followed by 9 digits is assumed local and prefixed
          with ``default_cc`` (typically the caller's country dial code).
        * Anything already starting with '+' is validated against E164_RE.
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith("00"):
        s = "+" + s[2:]
    # Strip everything that's not digits or leading '+'.
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if plus:
        candidate = "+" + digits
    elif digits.startswith("0") and len(digits) >= 9:
        candidate = default_cc + digits.lstrip("0")
    else:
        candidate = "+" + digits
    return candidate if E164_RE.match(candidate) else None


# ── Friendship helpers ────────────────────────────────────────────────────
async def link_bidirectional(db, user_a: str, user_b: str) -> None:
    """Add each user to the other's ``friends`` array (idempotent)."""
    if not user_a or not user_b or user_a == user_b:
        return
    await db.users.update_one(
        {"user_id": user_a},
        {"$addToSet": {"friends": user_b}},
    )
    await db.users.update_one(
        {"user_id": user_b},
        {"$addToSet": {"friends": user_a}},
    )


async def are_friends(db, a: str, b: str) -> bool:
    if not a or not b:
        return False
    u = await db.users.find_one({"user_id": a}, {"_id": 0, "friends": 1})
    return bool(u and b in (u.get("friends") or []))


# ── Search: email / phone / referral code ─────────────────────────────────
def _detect_query_type(q: str) -> str:
    """Return 'email', 'phone', 'code' based on the shape of ``q``."""
    q = (q or "").strip()
    if "@" in q:
        return "email"
    # A referral code is short, all-caps, and MUST contain at least one letter
    # so a pure digit sequence like "0760071445" is correctly treated as phone.
    if re.fullmatch(r"[A-Z0-9]{4,10}", q.upper()) and re.search(r"[A-Z]", q.upper()):
        return "code"
    return "phone"


async def search_user(db, query: str, default_cc: str = "+33") -> Optional[dict]:
    """Locate a user by email, referral code or phone (auto-detected)."""
    q = (query or "").strip()
    if not q:
        return None
    kind = _detect_query_type(q)
    if kind == "email":
        return await db.users.find_one({"email": q.lower()}, {"_id": 0})
    if kind == "code":
        return await db.users.find_one({"referral_code": q.upper()}, {"_id": 0})
    # Phone: normalise before hitting Mongo.
    phone = normalize_phone(q, default_cc=default_cc)
    if not phone:
        return None
    return await db.users.find_one({"phone": phone}, {"_id": 0})


# ── Friend requests ───────────────────────────────────────────────────────
async def create_request(
    db, from_uid: str, to_uid: str, source: str = "search",
) -> Optional[dict]:
    """Create a pending friend request unless already friends or duplicate.

    Returns the created request document, or None if no-op (already friends,
    duplicate pending, or self-request).
    """
    if not from_uid or not to_uid or from_uid == to_uid:
        return None
    if await are_friends(db, from_uid, to_uid):
        return None
    # Merge pending requests in both directions: if the target already sent me
    # one, auto-accept it instead of creating a mirror request.
    existing = await db.friend_requests.find_one({
        "$or": [
            {"from_user_id": from_uid, "to_user_id": to_uid, "status": "pending"},
            {"from_user_id": to_uid, "to_user_id": from_uid, "status": "pending"},
        ],
    }, {"_id": 0})
    if existing:
        return existing
    doc = {
        "id": uuid.uuid4().hex,
        "from_user_id": from_uid,
        "to_user_id": to_uid,
        "status": "pending",
        "source": source,
        "created_at": datetime.now(timezone.utc),
        "accepted_at": None,
    }
    await db.friend_requests.insert_one(doc)
    # Drop the Mongo _id so the doc is JSON-serialisable when returned to the
    # client (motor mutates the input dict in-place with an ObjectId).
    doc.pop("_id", None)
    return doc


async def accept_request(db, req_id: str, acting_uid: str) -> Optional[dict]:
    """Accept a pending request addressed to ``acting_uid``.

    Returns the updated request (with ``accepted_at``) or None if the request
    doesn't exist / is not pending / doesn't belong to the caller.
    """
    req = await db.friend_requests.find_one({"id": req_id}, {"_id": 0})
    if not req or req.get("status") != "pending":
        return None
    if req.get("to_user_id") != acting_uid:
        return None
    now = datetime.now(timezone.utc)
    await db.friend_requests.update_one(
        {"id": req_id},
        {"$set": {"status": "accepted", "accepted_at": now}},
    )
    await link_bidirectional(db, req["from_user_id"], req["to_user_id"])
    req["status"] = "accepted"
    req["accepted_at"] = now
    return req


async def reject_request(db, req_id: str, acting_uid: str) -> bool:
    """Drop a pending request. Either the recipient (reject) or the original
    sender (cancel) can call this — status becomes ``rejected`` / ``cancelled``
    accordingly. Returns True on success."""
    req = await db.friend_requests.find_one({"id": req_id}, {"_id": 0})
    if not req or req.get("status") != "pending":
        return False
    if req.get("to_user_id") != acting_uid and req.get("from_user_id") != acting_uid:
        return False
    status = "rejected" if req.get("to_user_id") == acting_uid else "cancelled"
    await db.friend_requests.update_one(
        {"id": req_id},
        {"$set": {"status": status}},
    )
    return True
