"""Auth primitives extracted from ``server.py`` (P0 decouple).

Contains only *pure* / DB-touching helpers — no HTTP glue. Endpoints stay
in ``routers/auth.py`` and continue to import both this module AND
``server`` (for shared models). ``server.py`` re-exports every symbol
below to keep the ``import server as srv`` API stable for existing
routers.

Public API (all symbols also re-exported by ``server.py``):
    - JWT_SECRET, JWT_ALGO, JWT_EXPIRE_DAYS
    - DEV_BYPASS_EMAILS
    - hash_password / verify_password
    - make_jwt
    - is_dev_user
    - get_user_by_token / current_user  (async DB lookups)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, Request

from core.db import db

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JWT_SECRET: str = os.environ.get("JWT_SECRET", "signmar-dev-secret-change-me")
JWT_ALGO: str = "HS256"
JWT_EXPIRE_DAYS: int = 7

# Dev / QA bypass — these accounts skip all "at sea" server-side checks
# so the maintainer can create/edit/confirm reports from a desk.
DEV_BYPASS_EMAILS: set[str] = {
    "antoninlepinay@gmail.com",
}
# 17/07/2026 — comptes créés uniquement par téléphone (pas d'email) : on
# étend le bypass aux numéros E.164 pour l'armateur qui teste depuis la
# terre avec un compte secondaire (Aslak). Ajouter ici les numéros au
# format canonique (+33XXXXXXXXX).
DEV_BYPASS_PHONES: set[str] = {
    "+33766071445",   # Aslak (compte secondaire armateur, tests terre)
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def make_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": _now_utc() + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": _now_utc(),
        "type": "jwt",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def is_dev_user(u: Optional[dict]) -> bool:
    """True for maintainer's dev account(s) — all Phase 2 rules are skipped.
    Match par EMAIL (compte principal armateur) OU par TÉLÉPHONE E.164
    (comptes secondaires OTP-only ajoutés à DEV_BYPASS_PHONES)."""
    if not u:
        return False
    email = (u.get("email") or "").lower().strip()
    if email and email in DEV_BYPASS_EMAILS:
        return True
    phone = (u.get("phone") or "").strip()
    if phone and phone in DEV_BYPASS_PHONES:
        return True
    return False


async def get_user_by_token(token: str) -> Optional[dict]:
    """Resolve a token (JWT or Google session_token) to a user."""
    if not token:
        return None

    # 1) JWT (email/password flow)
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        uid = payload.get("sub")
        if uid:
            u = await db.users.find_one({"user_id": uid}, {"_id": 0})
            if u:
                return u
    except Exception:
        pass

    # 2) Emergent Google session
    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not sess:
        return None
    if _ensure_aware(sess["expires_at"]) < _now_utc():
        return None
    return await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})


async def current_user(request: Request) -> dict:
    """FastAPI dependency-style helper: extract & validate the caller token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth[7:].strip()
    user = await get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


__all__ = [
    "JWT_SECRET", "JWT_ALGO", "JWT_EXPIRE_DAYS",
    "DEV_BYPASS_EMAILS", "DEV_BYPASS_PHONES",
    "hash_password", "verify_password", "make_jwt",
    "is_dev_user", "get_user_by_token", "current_user",
]
