"""SignalMar — Logique OTP téléphone (Phase A).

Stockage MongoDB dans ``otp_codes`` (index unique sur ``phone`` + TTL sur
``expires_at`` créés dans server.py). Le code n'est JAMAIS stocké en clair :
on garde ``sha256(phone:code)``.

Garde-fous (en plus du rate-limit SlowAPI par IP) :
    * Cooldown de 30 s entre deux envois vers le même numéro.
    * Max 5 envois / heure / numéro.
    * Max 5 tentatives de vérification par code, puis invalidation.
    * Expiration du code après 5 minutes.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

OTP_TTL_SECONDS = 300           # 5 min de validité
RESEND_COOLDOWN_SECONDS = 30    # délai mini entre 2 SMS
MAX_SENDS_PER_HOUR = 5          # par numéro
MAX_VERIFY_ATTEMPTS = 5         # par code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hash(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}".encode("utf-8")).hexdigest()


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def request_code(db, phone: str, fixed_code: Optional[str], skip_quota: bool = False) -> dict:
    """Crée (ou remplace) le code OTP pour ``phone``.

    ``skip_quota=True`` (QA uniquement, header X-RateLimit-Bypass validé par
    le routeur) : ignore le cooldown et le plafond 5/h par numéro.

    Returns:
        {"ok": True, "code": str}            → SMS à envoyer
        {"ok": False, "retry_in": int}       → cooldown / quota atteint
    """
    now = _now()
    existing = await db.otp_codes.find_one({"phone": phone})
    sends: list[datetime] = []
    if existing:
        sends = [
            _aware(t) for t in existing.get("send_history", [])
            if _aware(t) > now - timedelta(hours=1)
        ]
        if not skip_quota:
            if sends:
                last = max(sends)
                elapsed = (now - last).total_seconds()
                if elapsed < RESEND_COOLDOWN_SECONDS:
                    return {"ok": False, "retry_in": int(RESEND_COOLDOWN_SECONDS - elapsed)}
            if len(sends) >= MAX_SENDS_PER_HOUR:
                oldest = min(sends)
                retry = int((oldest + timedelta(hours=1) - now).total_seconds())
                return {"ok": False, "retry_in": max(retry, 60)}

    code = fixed_code or generate_code()
    sends.append(now)
    await db.otp_codes.update_one(
        {"phone": phone},
        {"$set": {
            "phone": phone,
            "code_hash": _hash(phone, code),
            "created_at": now,
            "expires_at": now + timedelta(seconds=OTP_TTL_SECONDS),
            "attempts": 0,
            "send_history": sends,
        }},
        upsert=True,
    )
    return {"ok": True, "code": code}


async def check_code(db, phone: str, code: str) -> str:
    """Vérifie le code SANS le consommer (le succès n'efface pas le doc,
    l'appelant appelle ``consume`` après création/login réussi).

    Returns one of: "ok" | "not_found" | "expired" | "too_many" | "invalid"
    """
    doc = await db.otp_codes.find_one({"phone": phone})
    if not doc or not doc.get("code_hash"):
        return "not_found"
    if _aware(doc["expires_at"]) < _now():
        return "expired"
    if int(doc.get("attempts", 0)) >= MAX_VERIFY_ATTEMPTS:
        return "too_many"
    if doc["code_hash"] != _hash(phone, code):
        await db.otp_codes.update_one({"phone": phone}, {"$inc": {"attempts": 1}})
        return "invalid"
    return "ok"


async def consume(db, phone: str) -> None:
    """Invalide le code après une auth réussie (garde l'historique d'envois
    pour que le quota horaire reste effectif)."""
    await db.otp_codes.update_one(
        {"phone": phone},
        {"$unset": {"code_hash": ""}, "$set": {"attempts": 0}},
    )
