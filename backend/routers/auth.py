"""Authentication & session routes.

Endpoints (mounted under /api):
- POST /api/auth/otp/request   → Phase A: send SMS OTP (mocked → 123456)
- POST /api/auth/otp/verify    → Phase A: verify OTP → login or signup + JWT
- POST /api/auth/register      → email registration + JWT (legacy/QA only)
- POST /api/auth/login         → email login + JWT (legacy/QA only)
- POST /api/auth/google/session → Emergent Google session exchange
- GET  /api/auth/me            → current user
- PATCH /api/auth/me           → edit pseudo (Phase A)
- POST /api/auth/logout        → invalidate session
- POST /api/register-push      → register a push token with Emergent relay

This module deliberately re-uses helpers from ``server`` rather than
re-implementing them, so the refactor is purely a code-layout change
(no behavioural diff). Tests must pass identically before/after.

Note: ``from __future__ import annotations`` was intentionally NOT added
here — the combination with ``@limiter.limit`` + FastAPI 0.110.1 breaks
Pydantic ForwardRef resolution for Body params on decorated endpoints.
"""

import os
import re
from datetime import timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

import server as srv
from server import RegisterIn, LoginIn, GoogleSessionIn
from core import referral as REF
from core import friends as FR
from core import otp as OTP
from core.sms import get_sms_sender, MockSmsSender
from core.rate_limit import (
    AUTH_LIMIT,
    GOOGLE_SESSION_LIMIT,
    LOGOUT_LIMIT,
    OTP_REQUEST_LIMIT,
    OTP_VERIFY_LIMIT,
    limiter,
)

router = APIRouter(tags=["auth"])

# Phase A — France uniquement pour l'instant (mobile 06/07 en E.164).
FR_MOBILE_RE = re.compile(r"^\+33[67]\d{8}$")

# Hard-reserved pseudonyms — only the maintainer may use them.
RESERVED_PSEUDOS = {"signalmar", "admin", "moderator", "amiral", "snsm"}


def _normalize_fr_mobile(raw: str) -> str:
    """0612345678 / +33612345678 → +33612345678, sinon HTTP 422."""
    phone = FR.normalize_phone(raw, default_cc="+33")
    if not phone or not FR_MOBILE_RE.match(phone):
        raise HTTPException(
            status_code=422,
            detail="Numéro de mobile français invalide (06 ou 07 attendu).",
        )
    return phone


async def _assert_pseudo_available(
    pseudo: str,
    exclude_user_id: Optional[str] = None,
    allow_reserved: bool = False,
):
    """Réservé + unicité (insensible à la casse). Lève HTTP 409 sinon."""
    if not allow_reserved and pseudo.lower() in RESERVED_PSEUDOS:
        raise HTTPException(status_code=409, detail="Ce pseudo est réservé.")
    safe = re.escape(pseudo)
    q: dict = {"pseudo": {"$regex": f"^{safe}$", "$options": "i"}}
    if exclude_user_id:
        q["user_id"] = {"$ne": exclude_user_id}
    clash = await srv.db.users.find_one(q, {"_id": 0, "user_id": 1})
    if clash:
        raise HTTPException(status_code=409, detail="Ce pseudo est déjà pris.")


# ----------------------------- OTP TÉLÉPHONE (Phase A) ----------------------
class OtpRequestIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)


class OtpVerifyIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    code: str = Field(min_length=4, max_length=8)
    # Requis uniquement pour la création de compte (numéro inconnu).
    pseudo: Optional[str] = Field(default=None, max_length=24)
    referral_code: Optional[str] = Field(default=None, max_length=16)


@router.post("/auth/otp/request")
@limiter.limit(OTP_REQUEST_LIMIT)
async def otp_request(request: Request, body: OtpRequestIn = Body(...)):
    """Envoie un code OTP au numéro (mocké : code fixe 123456).

    Retourne ``account_exists`` pour que le client sache s'il doit
    demander un pseudo (nouveau compte) avant la vérification.
    """
    phone = _normalize_fr_mobile(body.phone)
    sender = get_sms_sender()
    # QA : le header X-RateLimit-Bypass (même token que core.rate_limit)
    # saute AUSSI le quota par NUMÉRO (5/h) — indispensable aux tests
    # automatisés qui enchaînent les connexions OTP. Jamais exposé au client.
    bypass_token = os.environ.get("RATE_LIMIT_BYPASS_TOKEN", "")
    qa_bypass = bool(bypass_token) and request.headers.get("x-ratelimit-bypass") == bypass_token
    result = await OTP.request_code(srv.db, phone, sender.fixed_code(), skip_quota=qa_bypass)
    if not result["ok"]:
        raise HTTPException(
            status_code=429,
            detail=f"Trop de demandes. Réessayez dans {result['retry_in']} s.",
        )
    sent = await sender.send(
        phone, f"SignalMar : votre code de connexion est {result['code']}."
    )
    if not sent:
        raise HTTPException(status_code=502, detail="Envoi du SMS impossible. Réessayez.")
    existing = await srv.db.users.find_one({"phone": phone}, {"_id": 0, "user_id": 1})
    return {
        "sent": True,
        "account_exists": bool(existing),
        "mock": isinstance(sender, MockSmsSender),
        "cooldown": OTP.RESEND_COOLDOWN_SECONDS,
    }


@router.post("/auth/otp/verify")
@limiter.limit(OTP_VERIFY_LIMIT)
async def otp_verify(request: Request, body: OtpVerifyIn = Body(...)):
    """Vérifie le code OTP → connexion (numéro connu) ou création de compte
    (numéro inconnu, ``pseudo`` requis). Retourne ``{token, user}``."""
    phone = _normalize_fr_mobile(body.phone)
    status = await OTP.check_code(srv.db, phone, body.code.strip())
    if status in ("not_found", "expired"):
        raise HTTPException(
            status_code=410, detail="Code expiré. Demandez un nouveau code."
        )
    if status == "too_many":
        raise HTTPException(
            status_code=429,
            detail="Trop de tentatives. Demandez un nouveau code.",
        )
    if status == "invalid":
        raise HTTPException(status_code=401, detail="Code incorrect.")

    user = await srv.db.users.find_one({"phone": phone}, {"_id": 0})
    if user:
        uid = user["user_id"]
        await srv.db.users.update_one(
            {"user_id": uid}, {"$set": {"phone_verified": True}}
        )
    else:
        # ── Création de compte : pseudo obligatoire ──────────────────────
        pseudo = (body.pseudo or "").strip()
        if len(pseudo) < 3:
            raise HTTPException(
                status_code=422,
                detail="Choisissez un pseudo (3 caractères minimum) pour créer votre compte.",
            )
        await _assert_pseudo_available(pseudo)
        uid = srv.make_user_id()
        import hashlib
        await srv.db.users.insert_one({
            "user_id": uid,
            "email": None,
            "phone": phone,
            "phone_hash": hashlib.sha256(phone.encode("utf-8")).hexdigest(),
            "phone_verified": True,
            "name": pseudo,
            "pseudo": pseudo,
            "password_hash": None,
            "provider": "phone",
            "picture": "",
            "points": 0,
            "created_at": srv.now_utc(),
        })
        # Même pipeline parrainage que l'inscription email (Phase 3a/3b/B).
        await REF.ensure_referral_code(srv.db, uid)
        linked = await REF.attach_referrer(srv.db, uid, body.referral_code)
        if linked:
            referrer = await REF.resolve_referrer(srv.db, body.referral_code)
            if referrer:
                await FR.link_bidirectional(srv.db, uid, referrer["user_id"])
                from core import subscription as SUB
                await SUB.create_pending_referral(
                    srv.db, referrer["user_id"], uid, body.referral_code or "",
                )
        # 10/07/2026 — le filleul a créé son compte : ses invitations de
        # parrainage en attente sont consommées (choix définitif).
        from routers.referral_invites import delete_for_phone_hash
        await delete_for_phone_hash(
            srv.db, hashlib.sha256(phone.encode("utf-8")).hexdigest(),
        )

    await OTP.consume(srv.db, phone)
    token = srv.make_jwt(uid)
    fresh = await srv.db.users.find_one({"user_id": uid}, {"_id": 0})
    return {"token": token, "user": srv.serialize_user(fresh)}


@router.post("/auth/register")
@limiter.limit(AUTH_LIMIT)
async def register(request: Request, body: RegisterIn = Body(...)):
    # Phase 3b — at least one of email/phone must be present.
    if not body.email and not body.phone:
        raise HTTPException(
            status_code=422,
            detail="Un email ou un numéro de téléphone est requis.",
        )
    # Normalise phone (accept 0760071445 → +33760071445, or +33... → itself).
    phone = FR.normalize_phone(body.phone) if body.phone else None
    if body.phone and not phone:
        raise HTTPException(status_code=422, detail="Numéro de téléphone invalide.")
    if body.email:
        existing_email = await srv.db.users.find_one({"email": body.email.lower()}, {"_id": 0})
        if existing_email:
            raise HTTPException(status_code=400, detail="Email déjà utilisé.")
    if phone:
        existing_phone = await srv.db.users.find_one({"phone": phone}, {"_id": 0})
        if existing_phone:
            raise HTTPException(status_code=400, detail="Numéro déjà utilisé.")
    uid = srv.make_user_id()
    # Phase 4.2 — Contact sync. Users who register with a phone number can
    # be matched by their contacts via SHA-256(E.164) hashes (privacy-safe,
    # the raw number never leaves the address book). We precompute + store
    # the hash on signup so the /contacts/match endpoint is O(1) per hash.
    import hashlib
    phone_hash = hashlib.sha256(phone.encode("utf-8")).hexdigest() if phone else None
    user = {
        "user_id": uid,
        "email": body.email.lower() if body.email else None,
        "phone": phone,
        "phone_hash": phone_hash,
        "name": body.name,
        "pseudo": srv.make_pseudo(),
        "password_hash": srv.hash_password(body.password),
        "provider": "email",
        "picture": "",
        "points": 0,
        "created_at": srv.now_utc(),
    }
    await srv.db.users.insert_one(user)
    # Phase 3a — generate a unique referral code + attach the invite (if any)
    # BEFORE we serialize the response so the client immediately sees both.
    await REF.ensure_referral_code(srv.db, uid)
    linked = await REF.attach_referrer(srv.db, uid, body.referral_code)
    # Phase 3b — a valid referral link is treated as an auto-accepted
    # friendship (no request/accept ping-pong).
    if linked:
        referrer = await REF.resolve_referrer(srv.db, body.referral_code)
        if referrer:
            await FR.link_bidirectional(srv.db, uid, referrer["user_id"])
            # Phase B — start tracking the referral bonus (1 free month
            # of Premium if the referee posts a signalement confirmed
            # by an external member). Caps enforced inside.
            from core import subscription as SUB
            await SUB.create_pending_referral(
                srv.db, referrer["user_id"], uid, body.referral_code or "",
            )
    if phone_hash:
        # 10/07/2026 — consommer les invitations de parrainage en attente.
        from routers.referral_invites import delete_for_phone_hash
        await delete_for_phone_hash(srv.db, phone_hash)
    token = srv.make_jwt(uid)
    fresh = await srv.db.users.find_one({"user_id": uid}, {"_id": 0})
    return {"token": token, "user": srv.serialize_user(fresh)}


@router.post("/auth/login")
@limiter.limit(AUTH_LIMIT)
async def login(request: Request, body: LoginIn = Body(...)):
    u = await srv.db.users.find_one({"email": body.email.lower()}, {"_id": 0})
    if (
        not u
        or not u.get("password_hash")
        or not srv.verify_password(body.password, u["password_hash"])
    ):
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    token = srv.make_jwt(u["user_id"])
    return {"token": token, "user": srv.serialize_user(u)}


@router.post("/auth/google/session")
@limiter.limit(GOOGLE_SESSION_LIMIT)
async def google_session(request: Request, body: GoogleSessionIn = Body(...)):
    """Exchange Emergent session_id → session_token + create/update user."""
    async with httpx.AsyncClient(timeout=15) as h:
        r = await h.get(
            srv.EMERGENT_SESSION_URL, headers={"X-Session-ID": body.session_id}
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Session Google invalide")
    data = r.json()
    email = (data.get("email") or "").lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email Google manquant")

    existing = await srv.db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        uid = existing["user_id"]
        await srv.db.users.update_one(
            {"user_id": uid},
            {"$set": {
                "name": data.get("name") or existing.get("name", ""),
                "picture": data.get("picture") or existing.get("picture", ""),
                "provider": existing.get("provider", "google"),
            }},
        )
    else:
        uid = srv.make_user_id()
        await srv.db.users.insert_one({
            "user_id": uid,
            "email": email,
            "name": data.get("name") or email.split("@")[0],
            "pseudo": srv.make_pseudo(),
            "picture": data.get("picture") or "",
            "provider": "google",
            "points": 0,
            "created_at": srv.now_utc(),
        })
        # Phase 3a — same referral pipeline for the Google signup path.
        await REF.ensure_referral_code(srv.db, uid)
        linked = await REF.attach_referrer(srv.db, uid, body.referral_code)
        if linked:
            referrer = await REF.resolve_referrer(srv.db, body.referral_code)
            if referrer:
                from core import subscription as SUB
                await SUB.create_pending_referral(
                    srv.db, referrer["user_id"], uid, body.referral_code or "",
                )

    session_token = data["session_token"]
    await srv.db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {
            "session_token": session_token,
            "user_id": uid,
            "expires_at": srv.now_utc() + timedelta(days=7),
            "created_at": srv.now_utc(),
        }},
        upsert=True,
    )
    user = await srv.db.users.find_one({"user_id": uid}, {"_id": 0})
    return {"token": session_token, "user": srv.serialize_user(user)}


@router.get("/auth/me")
async def me(request: Request):
    u = await srv.current_user(request)
    # Phase 3a — backfill legacy accounts with a referral code lazily so the
    # Friends screen and the share button always have something to display.
    if not u.get("referral_code"):
        await REF.ensure_referral_code(srv.db, u["user_id"])
        u = await srv.db.users.find_one({"user_id": u["user_id"]}, {"_id": 0})
    return srv.serialize_user(u)


class ProfilePatchIn(BaseModel):
    pseudo: Optional[str] = Field(default=None, min_length=3, max_length=24)


@router.patch("/auth/me")
async def patch_me(body: ProfilePatchIn, request: Request):
    """Allow the signed-in user to edit their public pseudo.

    Phase A: server-side uniqueness check + reserved-name guard.
    """
    u = await srv.current_user(request)
    update: dict = {}
    if body.pseudo is not None:
        new_pseudo = body.pseudo.strip()
        await _assert_pseudo_available(
            new_pseudo,
            exclude_user_id=u["user_id"],
            allow_reserved=srv.is_dev_user(u),
        )
        update["pseudo"] = new_pseudo
    if not update:
        raise HTTPException(status_code=400, detail="Aucune modification fournie.")
    await srv.db.users.update_one({"user_id": u["user_id"]}, {"$set": update})
    fresh = await srv.db.users.find_one({"user_id": u["user_id"]}, {"_id": 0})
    return srv.serialize_user(fresh)


@router.post("/auth/logout")
@limiter.limit(LOGOUT_LIMIT)
async def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        await srv.db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


# ----------------------------- PUSH NOTIFICATIONS ---------------------------
@router.post("/register-push", status_code=201)
async def register_push(body: "srv.RegisterPushIn"):
    """Relay push-token registration to the Emergent push service."""
    try:
        resp = await srv._push_client.post(
            "/api/v1/push/users/register", json=body.model_dump()
        )
    except Exception as e:
        srv.logger.warning("register-push transport error: %s", e)
        raise HTTPException(status_code=502, detail="Push provider unavailable")
    if resp.status_code == 401:
        raise HTTPException(status_code=500, detail="EMERGENT_PUSH_KEY invalid")
    if resp.status_code >= 500:
        raise HTTPException(status_code=502, detail="Push provider unavailable")
    if resp.status_code >= 400:
        srv.logger.warning(
            "register-push upstream %s: %s", resp.status_code, resp.text[:200]
        )
    return {"status": "registered"}
