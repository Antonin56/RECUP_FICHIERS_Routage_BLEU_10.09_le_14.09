"""Phase T — Test-account fast switcher (dev/QA convenience).

This router exposes two POST-only endpoints that allow a small hard-coded
whitelist of email addresses (the SignalMar founders + private beta
testers) to jump instantly between test accounts *without* having to log
out / retype credentials. The purpose is purely operational — it makes
end-to-end validation of the Groups phase (creating a group with account
A, joining from account B, chatting from account C) painless.

Security posture — deliberate, but tight:
  1. Every endpoint requires a valid Bearer token from an *already*
     whitelisted account. Anyone else gets 403 immediately.
  2. The target account must also be in the whitelist. A whitelisted
     user can NEVER teleport into a random user.
  3. The whitelist is a compile-time constant; changing it requires a
     code change + redeploy.
  4. Switching preserves audit trail via the standard JWT (same signing
     secret, same payload shape, same expiry) — the switched-in session
     is indistinguishable from a fresh login for any downstream endpoint.
  5. This module is expected to remain available only until store
     launch + a short post-launch stabilisation window. Removing it is a
     one-file delete + `include_router` line removal.

Sensitive password mutation (bulk reset to `123454321`) is idempotent
and safe: it only fires at startup, only on the whitelisted emails.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import server as srv
from core import friends as FR
from core import referral as REF

logger = logging.getLogger("signalmar.dev_switch")


# 14/08/2026 (audit QA FND-042) — TOUT le routeur /api/dev/* est verrouillé
# par un drapeau SERVEUR : ``ALLOW_DEV_SWITCH=true`` doit être présent dans
# l'environnement (posé dans backend/.env en dev/préview, ABSENT en
# production → 403 systématique, même pour un compte whitelist).
def _require_dev_enabled() -> None:
    import os
    if os.environ.get("ALLOW_DEV_SWITCH", "").strip().lower() not in (
            "1", "true", "yes"):
        raise HTTPException(
            403, "Fonctions de développement désactivées sur ce serveur.")


router = APIRouter(tags=["dev"], dependencies=[Depends(_require_dev_enabled)])


# ── Whitelist (compile-time constant) ────────────────────────────────
# email → (target pseudo, phone in E.164). The founder account is included
# so the switcher can bounce back to admin instantly, but its pseudo is
# left untouched per user request.
TEST_ACCOUNTS: dict[str, dict[str, Optional[str]]] = {
    "antoninlepinay@gmail.com": {"pseudo": None, "phone": "+33760071445"},
}
# 10/09/2026 (contrôle pré-publication) — le mot de passe QA partagé n'est
# PLUS commité en dur : il vient de l'environnement (backend/.env en dev,
# Publish → Deploy → Secrets en production). Vide = seed QA DÉSACTIVÉ.
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "")


def _is_whitelisted(email: Optional[str]) -> bool:
    return bool(email) and email.lower() in TEST_ACCOUNTS


# ── Startup migration ────────────────────────────────────────────────
async def seed_test_accounts(db) -> dict:
    """Idempotent : make sure every whitelisted account exists with the
    correct pseudo, phone, phone_hash and shared test password.

    Returns a small report so the boot log makes it easy to debug.
    """
    created = 0
    updated = 0
    # Pas de TEST_PASSWORD dans l'environnement → aucun compte de test
    # seedé/réaligné (comportement voulu en production).
    if not TEST_PASSWORD:
        return {"created": 0, "updated": 0, "skipped": "TEST_PASSWORD non défini"}
    pwd_hash = srv.hash_password(TEST_PASSWORD)

    for email, cfg in TEST_ACCOUNTS.items():
        email_l = email.lower()
        u = await db.users.find_one({"email": email_l})
        phone = cfg.get("phone")
        pseudo = cfg.get("pseudo")
        phone_hash = (
            hashlib.sha256(phone.encode("utf-8")).hexdigest() if phone else None
        )
        if not u:
            uid = srv.make_user_id()
            doc: dict = {
                "user_id": uid,
                "email": email_l,
                "name": pseudo or "",
                "pseudo": pseudo or srv.make_pseudo(),
                "password_hash": pwd_hash,
                "provider": "email",
                "picture": "",
                "points": 0,
                "created_at": srv.now_utc(),
            }
            # Only insert phone fields when we actually have a phone — the
            # `phone_1` index is `unique + sparse`, but sparse only skips
            # MISSING fields, not null ones. Inserting {phone: null} would
            # collide with any other test account that has no phone.
            if phone:
                doc["phone"] = phone
                doc["phone_hash"] = phone_hash
            await db.users.insert_one(doc)
            await REF.ensure_referral_code(db, uid)
            created += 1
            logger.info("seeded test account %s -> %s", email_l, uid)
        else:
            patch: dict = {}
            # Always keep the password aligned with the shared test value so
            # a QA session never gets stuck on a stale hash.
            patch["password_hash"] = pwd_hash
            if pseudo and u.get("pseudo") != pseudo:
                patch["pseudo"] = pseudo
                patch["name"] = pseudo
            if phone and u.get("phone") != phone:
                patch["phone"] = phone
                patch["phone_hash"] = phone_hash
            if patch:
                await db.users.update_one({"user_id": u["user_id"]}, {"$set": patch})
                updated += 1
                # Ensure referral code exists on legacy accounts too.
                await REF.ensure_referral_code(db, u["user_id"])
    return {"created": created, "updated": updated, "total": len(TEST_ACCOUNTS)}


# ── HTTP endpoints ───────────────────────────────────────────────────
# 19/07/2026 (préparation bêta APK) : la bascule n'est PLUS ouverte à tous.
#   • ADMIN (whitelist email) : voit TOUS les comptes (recherche par
#     téléphone possible côté UI) et peut basculer vers n'importe lequel.
#   • BÊTA-TESTEUR (téléphone dans `beta_testers`) : voit et bascule
#     uniquement entre les comptes de la liste bêta (dont les siens).
#   • Autres : 403.
async def _switch_scope(me: dict) -> Optional[dict]:
    """Retourne le filtre Mongo des comptes accessibles, ou None si interdit."""
    from routers import beta as BETA
    if _is_whitelisted(me.get("email")):
        return {}  # admin : tous les comptes
    if await BETA.is_beta_tester(me):
        phones = await BETA.tester_phones()
        # Inclut toujours le compte courant pour pouvoir « revenir ».
        return {"$or": [
            {"phone": {"$in": sorted(phones)}},
            {"user_id": me["user_id"]},
        ]}
    return None


@router.get("/dev/test-accounts")
async def list_test_accounts(request: Request):
    me = await srv.current_user(request)
    scope = await _switch_scope(me)
    if scope is None:
        raise HTTPException(status_code=403, detail="Réservé aux comptes de test.")
    docs = await srv.db.users.find(
        scope,
        {"_id": 0, "user_id": 1, "email": 1, "phone": 1, "pseudo": 1,
         "picture": 1, "points": 1},
    ).to_list(500)
    # Compte courant en premier, puis alphabétique par pseudo.
    docs.sort(key=lambda d: (
        0 if d["user_id"] == me["user_id"] else 1,
        (d.get("pseudo") or "").lower(),
    ))
    return {
        "current_user_id": me["user_id"],
        "accounts": [
            {
                "user_id": d["user_id"],
                "email": d.get("email"),
                "phone": d.get("phone"),
                "pseudo": d.get("pseudo") or "",
                "picture": d.get("picture") or "",
                "points": d.get("points", 0),
                "is_current": d["user_id"] == me["user_id"],
            }
            for d in docs
        ],
    }


class SwitchIn(BaseModel):
    target_user_id: str = Field(..., description="user_id du compte cible (DEV)")


@router.post("/dev/switch-account")
async def switch_account(body: SwitchIn, request: Request):
    # 19/07/2026 : admin → n'importe quel compte ; bêta-testeur → uniquement
    # les comptes de la liste bêta ; autres → 403 (cf. _switch_scope).
    me = await srv.current_user(request)
    scope = await _switch_scope(me)
    if scope is None:
        raise HTTPException(status_code=403, detail="Réservé aux comptes de test.")
    query: dict = {"user_id": body.target_user_id}
    if scope:
        query = {"$and": [query, scope]}
    target = await srv.db.users.find_one(query, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="target_not_found")
    token = srv.make_jwt(target["user_id"])
    logger.info(
        "dev-switch %s (%s) -> %s (%s)",
        me.get("user_id"), me.get("pseudo"),
        target["user_id"], target.get("pseudo"),
    )
    return {"token": token, "user": srv.serialize_user(target)}


# ── Lot de signalements de TEST d'alarme (13/07/2026, demande user) ─────────
# POST /api/dev/alert-test-batch {lat, lng} — whitelist uniquement.
# Crée 5 signalements DÉCLENCHEURS D'ALARME en anneau autour de la position
# fournie (600 m / 1 / 3 / 10 / 20 km, caps espacés de 72°) et EFFACE le lot
# précédent (`is_alert_test` + author_id). Aucun point gagné, aucun push,
# aucun cône de dérive : purement destiné à tester le déclenchement des
# alertes sonores à bord.

class AlertTestBatchIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


# (distance km, cap °, type, sous-type, activity, extras)
ALERT_TEST_SPECS = [
    (0.6,  0,   "obstacle_nav", "ofni",                 None,      {}),
    (1.0,  72,  "animal_marin", "mammifere",            None,
     {"health": "alive_injured", "species": "common_dolphin"}),
    (3.0,  144, "autorites",    "gendarmerie_maritime", "control", {}),
    (10.0, 216, "pollution",    "pollution_locale",     None,      {}),
    (20.0, 288, "pollution",    "pollution_importante", None,      {}),
]


def _dest_point(lat: float, lng: float, bearing_deg: float, dist_km: float):
    """Point d'arrivée grande-cercle depuis (lat,lng) cap/distances donnés."""
    R = 6371.0
    br = math.radians(bearing_deg)
    lat1, lng1 = math.radians(lat), math.radians(lng)
    d = dist_km / R
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(br)
    )
    lng2 = lng1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), ((math.degrees(lng2) + 540) % 360) - 180


def _fmt_dist(km: float) -> str:
    return f"{int(km * 1000)} m" if km < 1 else f"{km:g} km"


@router.post("/dev/alert-test-batch")
async def create_alert_test_batch(body: AlertTestBatchIn, request: Request):
    from datetime import timedelta

    u = await srv.current_user(request)
    if not _is_whitelisted(u.get("email")):
        raise HTTPException(status_code=403, detail="Réservé aux comptes de test.")

    from routers.reports import _new_short_id

    deleted = await srv.db.reports.delete_many(
        {"is_alert_test": True, "author_id": u["user_id"]}
    )

    created = []
    for dist_km, bearing, rtype, subtype, activity, extras in ALERT_TEST_SPECS:
        lat, lng = _dest_point(body.lat, body.lng, bearing, dist_km)
        rid = srv.new_id()
        now = srv.now_utc()
        doc = {
            "id": rid,
            "short_id": await _new_short_id(),
            "type": rtype,
            "subtype": subtype,
            "lat": lat,
            "lng": lng,
            "origin_lat": lat,
            "origin_lng": lng,
            "description": f"🧪 TEST ALARME — {_fmt_dist(dist_km)} (cap {bearing}°)",
            "photos": [],
            "heading": None,
            "speed_knots": None,
            "extras": extras,
            "activity": activity,
            "author_id": u["user_id"],
            "author_pseudo": u.get("pseudo") or u.get("name", "Marin"),
            "author_name": u.get("name", ""),
            "created_at": now,
            "last_confirmed_at": now,
            "expires_at": now + timedelta(
                minutes=srv.effective_ttl_minutes(rtype, subtype)
            ),
            "confirmations": [],
            "is_alert_test": True,
        }
        await srv.db.reports.insert_one(doc)
        created.append({
            "id": rid, "distance_km": dist_km, "bearing": bearing,
            "type": rtype, "subtype": subtype, "lat": lat, "lng": lng,
        })

    logger.info(
        "alert-test-batch by %s: deleted=%d created=%d",
        u.get("email"), deleted.deleted_count, len(created),
    )
    return {"ok": True, "deleted": deleted.deleted_count, "created": created}
