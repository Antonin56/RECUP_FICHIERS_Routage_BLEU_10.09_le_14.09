"""Phase 4.1 — Private Groups foundations.

Mounted under ``/api``. All endpoints require authentication.

Groups are private-by-invite:
  * A user creates a group and becomes its ``owner``.
  * The owner shares an 8-char alphanumeric ``invite_code`` (via any Share sheet:
    WhatsApp, SMS, email, etc.). Anyone with the link/code can join provided
    the group is not full (hard cap: 20 members).
  * Only the owner can rename / delete / regenerate the invite / kick members.
  * Members can leave voluntarily; the owner must transfer ownership or delete
    the group before leaving.

MongoDB collections
-------------------
``groups``            {group_id, name, description, avatar_url, owner_id,
                       invite_code, invite_code_updated_at, created_at,
                       updated_at, member_count}
``group_members``     {membership_id, group_id, user_id, role, joined_at,
                       ghost_mode (default False), share_location (False),
                       muted (False), last_seen_at}

Indexes are declared in :func:`ensure_indexes` and are idempotent.
"""
from __future__ import annotations

import secrets
import string
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import server as srv

router = APIRouter(tags=["groups"])

# ── constants ────────────────────────────────────────────────────────────
MAX_MEMBERS = 20
INVITE_ALPHABET = string.ascii_uppercase + string.digits  # unambiguous enough
INVITE_LEN = 8
NAME_MIN, NAME_MAX = 2, 40
DESC_MAX = 240


# ── models ───────────────────────────────────────────────────────────────
class GroupCreateIn(BaseModel):
    name: str = Field(min_length=NAME_MIN, max_length=NAME_MAX)
    description: Optional[str] = Field(default="", max_length=DESC_MAX)
    avatar_url: Optional[str] = Field(default="", max_length=8192)  # allow data URIs


class GroupUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=NAME_MIN, max_length=NAME_MAX)
    description: Optional[str] = Field(default=None, max_length=DESC_MAX)
    avatar_url: Optional[str] = Field(default=None, max_length=8192)


# Phase 4.2b — Targeted invitations (no more code copy/paste flow).
# The admin picks contacts from their address book (already matched via
# SHA-256 phone hashes) and creates one `group_invitations` document per
# invitee. When the invitee opens SignalMar next, the app pulls their
# pending invites from `/groups/my-invitations` and shows them a big
# "Rejoindre / Décliner" card — no code to type.
class InviteBatchIn(BaseModel):
    user_ids: List[str] = Field(min_length=1, max_length=MAX_MEMBERS)


INVITE_TTL_DAYS = 30


# ── helpers ──────────────────────────────────────────────────────────────
def _new_invite_code() -> str:
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LEN))


async def _unique_invite_code(db) -> str:
    """Generate a code that is not already used by another group."""
    for _ in range(8):
        code = _new_invite_code()
        exists = await db.groups.find_one({"invite_code": code}, {"_id": 1})
        if not exists:
            return code
    # Astronomically unlikely to hit this — but degrade gracefully.
    return _new_invite_code() + secrets.token_hex(2).upper()


def _public_group(g: dict, my_role: Optional[str] = None) -> dict:
    return {
        "group_id": g.get("group_id"),
        "name": g.get("name") or "",
        "description": g.get("description") or "",
        "avatar_url": g.get("avatar_url") or "",
        "owner_id": g.get("owner_id"),
        "invite_code": g.get("invite_code"),
        "member_count": int(g.get("member_count") or 0),
        "max_members": MAX_MEMBERS,
        "my_role": my_role,
        "created_at": g.get("created_at"),
        "updated_at": g.get("updated_at"),
    }


def _public_member(u: dict, m: dict) -> dict:
    from core import points as PT
    return {
        "user_id": u.get("user_id"),
        "pseudo": u.get("pseudo") or u.get("name") or "Marin",
        "picture": u.get("picture", ""),
        "rank_label": srv.marine_rank(int(u.get("points", 0)))[1],
        "role": m.get("role") or "member",
        "joined_at": m.get("joined_at"),
        "reliability_score": PT.read_reliability(u) if hasattr(PT, "read_reliability") else None,
    }


async def _load_membership(db, group_id: str, user_id: str) -> Optional[dict]:
    return await db.group_members.find_one(
        {"group_id": group_id, "user_id": user_id}, {"_id": 0}
    )


async def _load_group(db, group_id: str) -> dict:
    g = await db.groups.find_one({"group_id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="group_not_found")
    return g


# ── endpoints ────────────────────────────────────────────────────────────
@router.post("/groups")
async def create_group(body: GroupCreateIn, request: Request):
    u = await srv.current_user(request)
    now = int(time.time())
    group_id = "grp_" + srv.new_id()
    invite = await _unique_invite_code(srv.db)
    doc = {
        "group_id": group_id,
        "name": body.name.strip(),
        "description": (body.description or "").strip(),
        "avatar_url": (body.avatar_url or "").strip(),
        "owner_id": u["user_id"],
        "invite_code": invite,
        "invite_code_updated_at": now,
        "created_at": now,
        "updated_at": now,
        "member_count": 1,
    }
    await srv.db.groups.insert_one(doc)
    await srv.db.group_members.insert_one({
        "membership_id": "gm_" + srv.new_id(),
        "group_id": group_id,
        "user_id": u["user_id"],
        "role": "owner",
        "joined_at": now,
        "ghost_mode": False,
        "share_location": False,
        "muted": False,
        "last_seen_at": now,
    })
    return _public_group(doc, my_role="owner")


@router.get("/groups")
async def list_my_groups(request: Request):
    u = await srv.current_user(request)
    memberships = [
        m async for m in srv.db.group_members.find(
            {"user_id": u["user_id"]}, {"_id": 0}
        )
    ]
    if not memberships:
        return {"groups": []}
    gids = [m["group_id"] for m in memberships]
    role_by_gid = {m["group_id"]: m.get("role") for m in memberships}
    groups = [
        g async for g in srv.db.groups.find({"group_id": {"$in": gids}}, {"_id": 0})
    ]
    # newest first
    groups.sort(key=lambda g: g.get("updated_at") or g.get("created_at") or 0, reverse=True)
    return {"groups": [_public_group(g, my_role=role_by_gid.get(g["group_id"])) for g in groups]}


@router.get("/groups/{group_id}")
async def get_group_detail(group_id: str, request: Request):
    u = await srv.current_user(request)
    membership = await _load_membership(srv.db, group_id, u["user_id"])
    if not membership:
        raise HTTPException(status_code=403, detail="not_a_member")
    g = await _load_group(srv.db, group_id)
    # Members list (owner first, then joined_at asc)
    members = [
        m async for m in srv.db.group_members.find({"group_id": group_id}, {"_id": 0})
    ]
    uids = [m["user_id"] for m in members]
    users = {
        uu["user_id"]: uu
        async for uu in srv.db.users.find({"user_id": {"$in": uids}}, {"_id": 0})
    }
    members_out = []
    for m in sorted(members, key=lambda x: (0 if x.get("role") == "owner" else 1, x.get("joined_at") or 0)):
        uu = users.get(m["user_id"])
        if uu:
            members_out.append(_public_member(uu, m))
    return {
        "group": _public_group(g, my_role=membership.get("role")),
        "members": members_out,
    }


@router.patch("/groups/{group_id}")
async def update_group(group_id: str, body: GroupUpdateIn, request: Request):
    u = await srv.current_user(request)
    g = await _load_group(srv.db, group_id)
    if g["owner_id"] != u["user_id"]:
        raise HTTPException(status_code=403, detail="only_owner_can_update")
    patch = {"updated_at": int(time.time())}
    if body.name is not None:
        patch["name"] = body.name.strip()
    if body.description is not None:
        patch["description"] = body.description.strip()
    if body.avatar_url is not None:
        patch["avatar_url"] = body.avatar_url.strip()
    await srv.db.groups.update_one({"group_id": group_id}, {"$set": patch})
    g.update(patch)
    return _public_group(g, my_role="owner")


@router.delete("/groups/{group_id}")
async def delete_group(group_id: str, request: Request):
    u = await srv.current_user(request)
    g = await _load_group(srv.db, group_id)
    if g["owner_id"] != u["user_id"]:
        raise HTTPException(status_code=403, detail="only_owner_can_delete")
    await srv.db.group_members.delete_many({"group_id": group_id})
    await srv.db.groups.delete_one({"group_id": group_id})
    # Phase 4.3/4.4 collections will be cleaned here too when they exist.
    await srv.db.group_messages.delete_many({"group_id": group_id})
    await srv.db.group_positions.delete_many({"group_id": group_id})
    return {"ok": True}


@router.post("/groups/{group_id}/regenerate-invite")
async def regenerate_invite(group_id: str, request: Request):
    u = await srv.current_user(request)
    g = await _load_group(srv.db, group_id)
    if g["owner_id"] != u["user_id"]:
        raise HTTPException(status_code=403, detail="only_owner_can_regenerate")
    code = await _unique_invite_code(srv.db)
    now = int(time.time())
    await srv.db.groups.update_one(
        {"group_id": group_id},
        {"$set": {"invite_code": code, "invite_code_updated_at": now, "updated_at": now}},
    )
    g.update({"invite_code": code, "invite_code_updated_at": now, "updated_at": now})
    return _public_group(g, my_role="owner")


@router.get("/groups/join/{invite_code}/preview")
async def preview_invite(invite_code: str, request: Request):
    """Public preview of a group by invite code — used to render the
    'do you want to join {name}?' confirmation UI before commiting."""
    await srv.current_user(request)  # must be authenticated
    code = (invite_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="invalid_code")
    g = await srv.db.groups.find_one({"invite_code": code}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="invite_not_found")
    # Owner pseudo (nice touch for the confirmation modal)
    owner = await srv.db.users.find_one({"user_id": g["owner_id"]}, {"_id": 0, "pseudo": 1, "picture": 1})
    return {
        "group_id": g["group_id"],
        "name": g.get("name") or "",
        "description": g.get("description") or "",
        "avatar_url": g.get("avatar_url") or "",
        "member_count": int(g.get("member_count") or 0),
        "max_members": MAX_MEMBERS,
        "owner_pseudo": (owner or {}).get("pseudo") or "Marin",
        "owner_picture": (owner or {}).get("picture") or "",
    }


@router.post("/groups/join/{invite_code}")
async def join_via_code(invite_code: str, request: Request):
    u = await srv.current_user(request)
    code = (invite_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="invalid_code")
    g = await srv.db.groups.find_one({"invite_code": code}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="invite_not_found")
    # Already a member?
    existing = await _load_membership(srv.db, g["group_id"], u["user_id"])
    if existing:
        return _public_group(g, my_role=existing.get("role"))
    # Capacity check
    if int(g.get("member_count") or 0) >= MAX_MEMBERS:
        raise HTTPException(status_code=409, detail="group_full")
    now = int(time.time())
    await srv.db.group_members.insert_one({
        "membership_id": "gm_" + srv.new_id(),
        "group_id": g["group_id"],
        "user_id": u["user_id"],
        "role": "member",
        "joined_at": now,
        "ghost_mode": False,
        "share_location": False,
        "muted": False,
        "last_seen_at": now,
    })
    await srv.db.groups.update_one(
        {"group_id": g["group_id"]},
        {"$inc": {"member_count": 1}, "$set": {"updated_at": now}},
    )
    g["member_count"] = int(g.get("member_count") or 0) + 1
    return _public_group(g, my_role="member")


@router.post("/groups/{group_id}/leave")
async def leave_group(group_id: str, request: Request):
    u = await srv.current_user(request)
    membership = await _load_membership(srv.db, group_id, u["user_id"])
    if not membership:
        raise HTTPException(status_code=404, detail="not_a_member")
    g = await _load_group(srv.db, group_id)
    if g["owner_id"] == u["user_id"]:
        raise HTTPException(
            status_code=409,
            detail="owner_must_delete_or_transfer",
        )
    await srv.db.group_members.delete_one(
        {"group_id": group_id, "user_id": u["user_id"]}
    )
    await srv.db.groups.update_one(
        {"group_id": group_id},
        {"$inc": {"member_count": -1}, "$set": {"updated_at": int(time.time())}},
    )
    return {"ok": True}


@router.post("/groups/{group_id}/kick/{user_id}")
async def kick_member(group_id: str, user_id: str, request: Request):
    u = await srv.current_user(request)
    g = await _load_group(srv.db, group_id)
    if g["owner_id"] != u["user_id"]:
        raise HTTPException(status_code=403, detail="only_owner_can_kick")
    if user_id == u["user_id"]:
        raise HTTPException(status_code=400, detail="cannot_kick_self")
    membership = await _load_membership(srv.db, group_id, user_id)
    if not membership:
        raise HTTPException(status_code=404, detail="not_a_member")
    await srv.db.group_members.delete_one({"group_id": group_id, "user_id": user_id})
    await srv.db.groups.update_one(
        {"group_id": group_id},
        {"$inc": {"member_count": -1}, "$set": {"updated_at": int(time.time())}},
    )
    # Phase 4.2c — Notify the kicked member (in-app + push if wired).
    # Kept minimal per product spec: just « Vous ne faites plus partie du
    # groupe X ». No mention of who kicked, no reason field — the
    # experience should feel neutral, not punitive.
    try:
        from core import notifications as N
        await N.create(
            srv.db, user_id,
            kind="group_kicked",
            title="Retiré d'un groupe",
            message=f"Vous ne faites plus partie du groupe « {g.get('name') or 'Groupe privé'} ».",
            action_url="/groups",
            payload={"group_id": group_id},
            dedup_key=f"kicked:{group_id}:{user_id}:{int(time.time())}",
        )
    except Exception as e:
        srv.logger.warning("kick notification failed: %s", e)
    return {"ok": True}


# ── Phase 4.2b — Direct invitations (no code copy/paste) ────────────────
def _public_invitation(inv: dict, group: dict, inviter: dict) -> dict:
    """Serialise a single pending invitation for the invitee UI."""
    return {
        "invite_id": inv.get("invite_id"),
        "group_id": group.get("group_id"),
        "group_name": group.get("name") or "",
        "group_description": group.get("description") or "",
        "group_avatar_url": group.get("avatar_url") or "",
        "group_member_count": int(group.get("member_count") or 0),
        "group_max_members": MAX_MEMBERS,
        "inviter_user_id": inviter.get("user_id"),
        "inviter_pseudo": inviter.get("pseudo") or inviter.get("name") or "Marin",
        "inviter_picture": inviter.get("picture") or "",
        "created_at": inv.get("created_at"),
        "expires_at": inv.get("expires_at"),
    }


@router.post("/groups/{group_id}/invitations")
async def create_invitations(group_id: str, body: InviteBatchIn, request: Request):
    """Admin creates one pending invitation per target user_id.

    - Only members of the group can invite (Phase 4.2b: any member; V2
      will restrict to owner + moderators once the role model expands).
    - Users already in the group are silently skipped (no-op).
    - Existing pending invitations are re-freshed (expires_at bumped) so
      the caller can safely retry.
    - Duplicated user_ids in the request are deduplicated.
    - Users who don't exist are ignored (edge case; the contact-sync
      pipeline that produced these IDs already verified they're valid).
    """
    u = await srv.current_user(request)
    membership = await _load_membership(srv.db, group_id, u["user_id"])
    if not membership:
        raise HTTPException(status_code=403, detail="not_a_member")
    g = await _load_group(srv.db, group_id)

    # De-dup and drop the caller themselves.
    targets = list({uid for uid in body.user_ids if uid and uid != u["user_id"]})
    if not targets:
        # All requested user_ids were the caller (or empty) — degrade
        # silently rather than throwing, so the client can send a raw
        # selection without pre-filtering. Consistent with the
        # already-member path below.
        return {
            "created": 0, "already_member": 0,
            "remaining_seats": MAX_MEMBERS - int(g.get("member_count") or 0),
            "invitations": [],
        }

    # Capacity guard : if inviting all of them at once would push the
    # group over max, we still create the invitations (they can decline
    # or be first-come-first-serve) but flag the caller.
    remaining_seats = MAX_MEMBERS - int(g.get("member_count") or 0)

    # Skip anyone who's already a member.
    existing_members = {
        m["user_id"] async for m in srv.db.group_members.find(
            {"group_id": group_id, "user_id": {"$in": targets}},
            {"_id": 0, "user_id": 1},
        )
    }
    fresh_targets = [t for t in targets if t not in existing_members]
    if not fresh_targets:
        return {"created": 0, "already_member": len(targets), "invitations": []}

    # Verify user existence + fetch names for the response payload.
    invitee_docs = {
        d["user_id"]: d async for d in srv.db.users.find(
            {"user_id": {"$in": fresh_targets}},
            {"_id": 0, "user_id": 1, "pseudo": 1, "name": 1, "picture": 1},
        )
    }
    fresh_targets = [t for t in fresh_targets if t in invitee_docs]

    now = int(time.time())
    ttl = now + INVITE_TTL_DAYS * 86400
    invitations = []
    for uid in fresh_targets:
        # Upsert on (group_id, invitee_user_id) so retries are idempotent.
        invite_id = "gi_" + srv.new_id()
        await srv.db.group_invitations.update_one(
            {"group_id": group_id, "invitee_user_id": uid,
             "status": {"$in": ["pending", "expired"]}},
            {
                "$setOnInsert": {
                    "invite_id": invite_id,
                    "group_id": group_id,
                    "invitee_user_id": uid,
                    "created_at": now,
                },
                "$set": {
                    "inviter_user_id": u["user_id"],
                    "status": "pending",
                    "expires_at": ttl,
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        # Re-read to get the canonical invite_id (upsert may have kept
        # the previous one).
        doc = await srv.db.group_invitations.find_one(
            {"group_id": group_id, "invitee_user_id": uid, "status": "pending"},
            {"_id": 0},
        )
        if doc:
            invitations.append(_public_invitation(doc, g, u))
    return {
        "created": len(invitations),
        "already_member": len(existing_members),
        "remaining_seats": remaining_seats,
        "invitations": invitations,
    }


@router.get("/invitations/mine")
async def list_my_invitations(request: Request):
    """Pending invitations for the current user, freshest first."""
    u = await srv.current_user(request)
    now = int(time.time())
    # Auto-expire on the fly to keep the list tight.
    await srv.db.group_invitations.update_many(
        {"invitee_user_id": u["user_id"], "status": "pending",
         "expires_at": {"$lt": now}},
        {"$set": {"status": "expired"}},
    )
    docs = [
        d async for d in srv.db.group_invitations.find(
            {"invitee_user_id": u["user_id"], "status": "pending"},
            {"_id": 0},
        ).sort("created_at", -1)
    ]
    if not docs:
        return {"invitations": []}

    gids = list({d["group_id"] for d in docs})
    inviter_ids = list({d["inviter_user_id"] for d in docs})
    groups_by = {
        g["group_id"]: g async for g in srv.db.groups.find(
            {"group_id": {"$in": gids}}, {"_id": 0},
        )
    }
    inviters_by = {
        uu["user_id"]: uu async for uu in srv.db.users.find(
            {"user_id": {"$in": inviter_ids}},
            {"_id": 0, "user_id": 1, "pseudo": 1, "name": 1, "picture": 1},
        )
    }
    out = []
    for d in docs:
        g = groups_by.get(d["group_id"])
        inviter = inviters_by.get(d["inviter_user_id"])
        if not g or not inviter:
            continue  # orphan invitation — skip silently
        out.append(_public_invitation(d, g, inviter))
    return {"invitations": out}


@router.post("/invitations/{invite_id}/accept")
async def accept_invitation(invite_id: str, request: Request):
    u = await srv.current_user(request)
    inv = await srv.db.group_invitations.find_one(
        {"invite_id": invite_id, "invitee_user_id": u["user_id"]},
        {"_id": 0},
    )
    if not inv:
        raise HTTPException(status_code=404, detail="invite_not_found")
    if inv.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"invite_{inv.get('status')}")
    g = await _load_group(srv.db, inv["group_id"])
    now = int(time.time())
    # Already a member? Mark the invite as accepted and return the group.
    membership = await _load_membership(srv.db, g["group_id"], u["user_id"])
    if not membership:
        if int(g.get("member_count") or 0) >= MAX_MEMBERS:
            raise HTTPException(status_code=409, detail="group_full")
        await srv.db.group_members.insert_one({
            "membership_id": "gm_" + srv.new_id(),
            "group_id": g["group_id"],
            "user_id": u["user_id"],
            "role": "member",
            "joined_at": now,
            "ghost_mode": False,
            "share_location": False,
            "muted": False,
            "last_seen_at": now,
        })
        await srv.db.groups.update_one(
            {"group_id": g["group_id"]},
            {"$inc": {"member_count": 1}, "$set": {"updated_at": now}},
        )
        g["member_count"] = int(g.get("member_count") or 0) + 1
    await srv.db.group_invitations.update_one(
        {"invite_id": invite_id},
        {"$set": {"status": "accepted", "responded_at": now}},
    )
    return _public_group(g, my_role="member")


@router.post("/invitations/{invite_id}/decline")
async def decline_invitation(invite_id: str, request: Request):
    u = await srv.current_user(request)
    inv = await srv.db.group_invitations.find_one(
        {"invite_id": invite_id, "invitee_user_id": u["user_id"]},
        {"_id": 0},
    )
    if not inv:
        raise HTTPException(status_code=404, detail="invite_not_found")
    if inv.get("status") != "pending":
        return {"ok": True}
    now = int(time.time())
    await srv.db.group_invitations.update_one(
        {"invite_id": invite_id},
        {"$set": {"status": "declined", "responded_at": now}},
    )
    return {"ok": True}


# ── indexes (called once at startup by server.py) ────────────────────────
async def ensure_indexes(db) -> None:
    await db.groups.create_index("group_id", unique=True)
    await db.groups.create_index("invite_code", unique=True)
    await db.groups.create_index("owner_id")
    await db.group_members.create_index([("group_id", 1), ("user_id", 1)], unique=True)
    await db.group_members.create_index("user_id")
    # Phase 4.2b — Targeted invitations.
    await db.group_invitations.create_index("invite_id", unique=True)
    await db.group_invitations.create_index(
        [("invitee_user_id", 1), ("status", 1), ("created_at", -1)],
    )
    await db.group_invitations.create_index(
        [("group_id", 1), ("invitee_user_id", 1), ("status", 1)],
    )
