"""SignMar backend — auth (email + Emergent Google), reports, chat, weather.

Refactor note (P0 decouple):
    Auth primitives, DB client, and drift-cone physics have been extracted
    to ``core.auth``, ``core.db``, and ``core.drift``. This module still
    re-exports every symbol they used to define at module scope so the
    existing ``import server as srv; srv.<symbol>`` API used by every
    router keeps working unchanged.
"""
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import hashlib
import html
import uuid
import logging
import httpx
import math
import base64
import io
from PIL import Image

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---------------------------------------------------------------------------
# P0 decouple — re-exports from core.* modules
# ---------------------------------------------------------------------------
from core.db import client, db, MONGO_URL, DB_NAME  # noqa: E402
from core.auth import (  # noqa: E402
    JWT_SECRET, JWT_ALGO, JWT_EXPIRE_DAYS,
    DEV_BYPASS_EMAILS,
    DEV_BYPASS_PHONES,
    hash_password, verify_password, make_jwt,
    is_dev_user, get_user_by_token, current_user,
)
from core.drift import (  # noqa: E402
    haversine_km, offset_point,
    DRIFT_LEEWAY, DRIFT_CONE_HALF_ANGLE_DEG, DRIFT_CONE_ARC_STEPS,
    DRIFT_CONE_HOURS, SUBTYPE_DRIFT,
    subtype_drift_weights, is_animal_dead, drift_cone_eligible,
    fetch_marine_drift_inputs, compute_drift_cone, refresh_drift_cone,
)

EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
EMERGENT_PUSH_BASE_URL = "https://integrations.emergentagent.com"
EMERGENT_PUSH_KEY = os.environ.get("EMERGENT_PUSH_KEY", "placeholder")
REPORT_TTL_HOURS = 48  # legacy purge floor (kept for the migration / cleanup job)
# Sliding lifetime applied to new + confirmed reports.
REPORT_DEFAULT_TTL_MIN = 60  # default lifetime of a fresh report
REPORT_CONFIRM_TTL_MIN = 60  # sliding extension granted on each confirmation
# Per-type / per-subtype TTL overrides (per cahier des charges 27/06).
# Lookup order: TTL_OVERRIDES[(type, subtype)] → TTL_OVERRIDES[(type, None)]
# → REPORT_DEFAULT_TTL_MIN.
TTL_OVERRIDES: dict = {
    ("autorites", None): 60,             # 1h
    ("obstacle_nav", None): 60,
    ("animal_marin", None): 360,         # 6h minimum even unconfirmed
    ("pollution", "pollution_cote"): 1440,       # 24h
    ("pollution", "pollution_locale"): 360,      # 6h
    ("pollution", "pollution_importante"): 720,  # 12h
    # 24/07/2026 — Phénomènes météo (orage, trombe, brume) : 2h par défaut.
    ("meteo", None): 120,
    ("autre", None): 60,
}


def effective_ttl_minutes(rtype: str, subtype: Optional[str] = None) -> int:
    """Lookup the sliding TTL for a given type / subtype combo."""
    if subtype:
        v = TTL_OVERRIDES.get((rtype, subtype))
        if v is not None:
            return v
    v = TTL_OVERRIDES.get((rtype, None))
    return v if v is not None else REPORT_DEFAULT_TTL_MIN
# Author self-edit constraints (Phase 2 rules).
AUTHOR_EDIT_MAX_RADIUS_KM = 1.0  # max shift radius for an author-direct edit
AUTHOR_DELETE_WEEKLY_LIMIT = 1   # max self-deletions allowed in a rolling week
# Geofencing: only allow create/edit/confirm "at sea" — Open-Meteo Marine API
# returns wave data for valid sea points only; inland / very-close-to-coast
# points return 400 or empty arrays. We cache the verdict at ~1 km precision
# in-memory (and persist in a small Mongo collection to survive restarts).
_sea_cache: dict[tuple[int, int], bool] = {}
# Dev / QA bypass emails + is_dev_user — moved to core.auth (re-exported above).

# Push relay client (Emergent-managed). Lazily initialised — closed on shutdown.
_push_client = httpx.AsyncClient(
    base_url=EMERGENT_PUSH_BASE_URL,
    headers={"X-Push-Key": EMERGENT_PUSH_KEY},
    timeout=10.0,
)


async def send_push(
    recipients: List[str],
    data: dict,
    idempotency_key: Optional[str] = None,
) -> None:
    """Server-side push relay + in-app notification persistence.

    V3c: every relay call also persists a row in the ``notifications``
    collection so the recipient will see the message in the bell drawer even
    if their push registration failed (typical in Expo Go / no Firebase).
    Failures are logged but never raised.
    """
    if not recipients:
        return
    if "title" not in data or "message" not in data:
        return
    # Persist in-app notification for each recipient (best-effort, silent).
    # Deferred import to avoid cycles at server.py load time.
    try:
        from core import notifications as NOTIF
        kind = str(data.get("kind") or "system")
        for uid in recipients:
            await NOTIF.create(
                db, uid,
                kind=kind,
                title=str(data.get("title") or ""),
                message=str(data.get("message") or ""),
                action_url=data.get("action_url") or None,
                dedup_key=idempotency_key,
            )
    except Exception as e:
        logging.getLogger("signmar").warning("notif persist failed: %s", e)
    payload: dict = {"recipients": recipients[:100], "data": data}
    if idempotency_key:
        payload["$idempotency_key"] = idempotency_key
    try:
        resp = await _push_client.post("/api/v1/push/trigger", json=payload)
        if resp.status_code >= 400:
            logging.getLogger("signmar").warning(
                "push relay non-2xx %s: %s", resp.status_code, resp.text[:200]
            )
    except Exception as e:
        logging.getLogger("signmar").warning("push relay failed: %s", e)

app = FastAPI(title="SignMar API")
api = APIRouter(prefix="/api")

# ─── P0 — Rate limiting (SlowAPI). Installed here so the exception handler
# is registered on the FastAPI app itself (per-endpoint decorators live in
# core.rate_limit + are applied inside routers/auth.py). ───
from slowapi.errors import RateLimitExceeded  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from core.rate_limit import limiter as _rl_limiter  # noqa: E402

app.state.limiter = _rl_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("signmar")

# ----------------------------- helpers --------------------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_user_id() -> str:
    return f"user_{uuid.uuid4().hex[:12]}"


def new_id() -> str:
    return uuid.uuid4().hex


# hash_password, verify_password, make_jwt — moved to core.auth (re-exported).

def ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def points_for_rank(points: int) -> str:
    if points >= 1500:
        return "Vigie communautaire"
    if points >= 500:
        return "Capitaine"
    if points >= 200:
        return "Skipper"
    if points >= 80:
        return "Chef de bord"
    if points >= 20:
        return "Équipier"
    return "Mousse"


# Phase D — Indice de fiabilité (0-100%, défaut 50%).
# Built from two raw counters on the user document:
#   - reliability_pos = (#own reports created) + (#confirmations of own reports)
#   - reliability_neg = (#own reports infirmed/marked fake/ended by community)
# Normalisation: pct = clamp(50 + (pos - neg) * 2, 0, 100). Each net event
# shifts the score by 2 percentage points so a small number of confirmations
# moves the needle without making the score swing wildly.
RELIABILITY_DEFAULT = 50
RELIABILITY_MIN = 0
RELIABILITY_MAX = 100
RELIABILITY_STEP_PCT = 2.0
# Phase E.3 — Cap (heading) editing: non-authors need at least this reliability
# score (in %) to update the heading on autorities / drift-eligible reports.
HEADING_EDIT_RELIABILITY_THRESHOLD = 60


def reliability_score(pos: int, neg: int) -> int:
    raw = RELIABILITY_DEFAULT + (int(pos) - int(neg)) * RELIABILITY_STEP_PCT
    return max(RELIABILITY_MIN, min(RELIABILITY_MAX, int(round(raw))))


def user_reliability(u: dict) -> int:
    # V1.2 — new source of truth is the reliability_pct field (0-100).
    # Falls back to the legacy pos/neg formula for accounts created before
    # the migration so they don't jump to a random value.
    from core.points import read_reliability
    return read_reliability(u)


# Marine rank ladder — mirror of `frontend/src/lib/marine-ranks.ts`. We expose
# only the id + label here; the icon/colour are resolved on the client. Mainly
# used to expose `rank_id` on the user serializer so the map markers can
# render a tiny galon overlay next to every report's author.
MARINE_RANK_LADDER = [
    ("mousse",            0,    "Mousse"),
    ("matelot",           24,   "Matelot"),
    ("qm2",               60,   "Quartier-maître 2ᵉ classe"),
    ("qm1",               120,  "Quartier-maître 1ʳᵉ classe"),
    ("second_maitre",     240,  "Second maître"),
    ("maitre",            420,  "Maître"),
    ("premier_maitre",    660,  "Premier maître"),
    ("maitre_principal",  960,  "Maître principal"),
    ("major",             1320, "Major"),
    ("aspirant",          1740, "Aspirant"),
    ("ev2",               2220, "Enseigne de vaisseau 2ᵉ classe"),
    ("ev1",               2760, "Enseigne de vaisseau 1ʳᵉ classe"),
    ("lv",                3360, "Lieutenant de vaisseau"),
    ("cc",                4020, "Capitaine de corvette"),
    ("cf",                4740, "Capitaine de frégate"),
    ("cv",                5520, "Capitaine de vaisseau"),
    ("contre_amiral",     6360, "Contre-amiral"),
    ("vice_amiral",       7260, "Vice-amiral"),
    ("vae",               8220, "Vice-amiral d'escadre"),
    ("amiral",            9240, "Amiral"),
    ("amiral_de_france",  10320, "Amiral de France"),
]


def marine_rank(points: int) -> tuple[str, str]:
    """Return (rank_id, rank_label) for the given point count."""
    cur = MARINE_RANK_LADDER[0]
    for entry in MARINE_RANK_LADDER:
        if points >= entry[1]:
            cur = entry
        else:
            break
    return cur[0], cur[2]


async def bump_reliability(user_id: Optional[str], *, pos: int = 0, neg: int = 0) -> None:
    """Adjust a user's reliability counters (best-effort, never raises)."""
    if not user_id or (pos == 0 and neg == 0):
        return
    inc: dict = {}
    if pos:
        inc["reliability_pos"] = int(pos)
    if neg:
        inc["reliability_neg"] = int(neg)
    try:
        await db.users.update_one({"user_id": user_id}, {"$inc": inc})
    except Exception as e:
        logger.warning("bump_reliability failed for %s: %s", user_id, e)


async def get_user_by_token(token: str) -> Optional[dict]:  # noqa: F811 — re-export
    """Wrapper around core.auth.get_user_by_token (kept for router compat)."""
    from core.auth import get_user_by_token as _core
    return await _core(token)


async def current_user(request: Request) -> dict:  # noqa: F811 — re-export
    """Wrapper around core.auth.current_user (kept for router compat)."""
    from core.auth import current_user as _core
    return await _core(request)


_NAUTICAL_PREFIXES = [
    "Marin", "Capitaine", "Skipper", "Navigateur", "Mousse", "Matelot",
    "Quartier-maitre", "Pilote", "Bosco", "Timonier", "Vigie", "Veilleur",
]


def make_pseudo() -> str:
    """Random pseudonymous nautical-style handle (e.g. 'Marin_4523').
    Generated server-side at registration so we never have to expose the real
    name. Users can customise via PATCH /auth/me later (Phase A).
    """
    import random
    return f"{random.choice(_NAUTICAL_PREFIXES)}_{random.randint(1000, 9999)}"


def serialize_user(u: dict) -> dict:
    pts = u.get("points", 0)
    # Phase A: pseudo is the public identity. Fall back to the legacy `name`
    # for pre-pseudo accounts; we'll backfill via a migration on first login.
    pseudo = u.get("pseudo") or u.get("name") or "Marin"
    rank_id, rank_label = marine_rank(pts)
    rel_pos = int(u.get("reliability_pos", 0))
    rel_neg = int(u.get("reliability_neg", 0))
    # V1.2 — reliability_pct is the source of truth (same helper as the
    # heading-edit enforcement in routers/reports.py, so the % the user sees
    # always matches what the server enforces). Legacy pos/neg fallback inside.
    rel = user_reliability(u)
    return {
        "user_id": u["user_id"],
        "email": u.get("email"),
        # Public identity → ALWAYS the pseudo (never the legal name).
        "pseudo": pseudo,
        "name": pseudo,  # legacy FE field still reads this; aliased to pseudo.
        # Custom title (e.g. "Amiral Modérateur" for the maintainer).
        "title": u.get("title"),
        "picture": u.get("picture", ""),
        "provider": u.get("provider", "email"),
        "points": pts,
        # Phase D — proper Marine Nationale rank (from MARINE_RANKS ladder).
        # The legacy `rank` field is preserved for backwards compat but now
        # mirrors the new Marine label so the "Capitaine doublon" disappears.
        "rank": rank_label,
        "rank_id": rank_id,
        "rank_label": rank_label,
        # Phase D — Indice de fiabilité (1-12), default 6.
        "reliability_score": rel,
        "reliability_pos": rel_pos,
        "reliability_neg": rel_neg,
        "notify_radius_km": float(u.get("notify_radius_km") or 15.0),
        "muted_types": list(u.get("muted_types") or []),
        # 13/07/2026 — position des boutons zoom sur la carte (déplaçables).
        "zoom_btn_pos": u.get("zoom_btn_pos"),
        "created_at": u.get("created_at"),
        "is_dev": (
            ((u.get("email") or "").lower() in DEV_BYPASS_EMAILS)
            or ((u.get("phone") or "") in DEV_BYPASS_PHONES)
        ),
        # Phase 3a — referral system: unique short code for share links + the
        # code of the friend who invited us (if any). Both are optional for
        # legacy accounts (backfilled lazily on first read via ensure_referral_code).
        "referral_code": u.get("referral_code"),
        "referred_by": u.get("referred_by"),
        # Phase 3b — E.164 phone number & explicit friends list (accepted
        # bidirectional friendships, includes referral-linked users).
        "phone": u.get("phone"),
        "friends_count": len(u.get("friends") or []),
        # 31/07/2026 — compte SignalMar admin (armateur) : débloque la fonction
        # « Capture & envoi au support » sur la carte + endpoints d'inspection.
        "is_signalmar_admin": _is_signalmar_admin_local(u),
        # 01/08/2026 — Moteur de routage actif (préférence utilisateur).
        # Par défaut ``engine_a`` (built-in). Modifié via
        # POST /api/routing/user/active-engine.
        "active_engine_id": u.get("active_engine_id") or "engine_a",
    }


def _is_signalmar_admin_local(u: dict) -> bool:
    """Wrapper local pour éviter un import circulaire au niveau module."""
    try:
        from core.support_admin import is_signalmar_admin
        return is_signalmar_admin(u)
    except Exception:
        return False


def haversine_km(*args, **kwargs):  # noqa: F811 — re-export shim
    """Re-export of core.drift.haversine_km for router compat."""
    from core.drift import haversine_km as _core
    return _core(*args, **kwargs)


def offset_point(*args, **kwargs):  # noqa: F811 — re-export shim
    """Re-export of core.drift.offset_point for router compat."""
    from core.drift import offset_point as _core
    return _core(*args, **kwargs)


# NOTE — Drift constants (DRIFT_LEEWAY, DRIFT_CONE_HALF_ANGLE_DEG,
# DRIFT_CONE_ARC_STEPS, DRIFT_CONE_HOURS, SUBTYPE_DRIFT) and predicates
# (subtype_drift_weights, is_animal_dead, drift_cone_eligible) plus the
# fetch/compute/refresh functions all now live in core.drift and are
# re-exported at the top of this module. The old inline definitions
# have been removed as part of the P0 decouple.


async def is_at_sea(lat: float, lng: float) -> bool:
    """Return True when the given point is open sea (≈ ≥ 1 km from the coast).

    Implementation note: we piggyback on the free Open-Meteo Marine API which
    only returns wave data for valid marine points. Inland points (cities,
    rivers, lakes) return HTTP 400 or empty hourly arrays. The verdict is
    cached at ~1 km precision (rounded lat/lng × 100) in-memory + persisted
    in Mongo, so we hit the API at most once per coastal cell.

    Open-Meteo enforces a soft rate limit (~10k/day, free) which is far
    above our needs given the cache. Failures fall back to "allow" — we
    never block a user because of a 3rd-party hiccup.
    """
    key = (int(round(lat * 100)), int(round(lng * 100)))
    if key in _sea_cache:
        return _sea_cache[key]
    # Persistent cache (survives restarts).
    try:
        cached = await db.sea_cache.find_one({"k": list(key)}, {"_id": 0, "v": 1})
        if cached is not None:
            _sea_cache[key] = bool(cached["v"])
            return _sea_cache[key]
    except Exception:
        pass
    verdict = True  # fail-open default
    try:
        async with httpx.AsyncClient(timeout=4.0) as cli:
            r = await cli.get(
                "https://marine-api.open-meteo.com/v1/marine",
                params={
                    "latitude": round(lat, 4),
                    "longitude": round(lng, 4),
                    "hourly": "wave_height",
                    "forecast_days": 1,
                },
            )
            if r.status_code != 200:
                verdict = False
            else:
                j = r.json()
                arr = ((j.get("hourly") or {}).get("wave_height")) or []
                verdict = any(v is not None for v in arr)
    except Exception as e:
        logger.warning("is_at_sea check failed (%s) → fail-open", e)
        verdict = True
    _sea_cache[key] = verdict
    try:
        await db.sea_cache.update_one(
            {"k": list(key)},
            {"$set": {"k": list(key), "v": verdict, "at": now_utc()}},
            upsert=True,
        )
    except Exception:
        pass
    return verdict


def _ensure_user_at_sea_field(u: dict) -> Optional[tuple[float, float]]:
    """Return (lat,lng) if the user has a recent fix (≤24h), else None."""
    lat = u.get("last_lat")
    lng = u.get("last_lng")
    at = u.get("last_loc_at")
    if lat is None or lng is None or at is None:
        return None
    if ensure_aware(at) < now_utc() - timedelta(hours=24):
        return None
    return float(lat), float(lng)


# ----------------------------- models ---------------------------------------
class RegisterIn(BaseModel):
    email: Optional[EmailStr] = None
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=60)
    # Phase 3b — E.164 phone number (e.g. "+33760071445"). At least one of
    # email/phone must be present; enforced in the /auth/register endpoint.
    phone: Optional[str] = Field(default=None, max_length=20)
    # Phase 3a — optional referral code entered by the user at signup, either
    # typed manually or auto-filled by the deep-link handler after tapping a
    # /join?ref=XXX invite.
    referral_code: Optional[str] = Field(default=None, max_length=16)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class GoogleSessionIn(BaseModel):
    session_id: str
    # Phase 3a — same optional referral code for Google-signup flow.
    referral_code: Optional[str] = Field(default=None, max_length=16)


class ReportType(str):
    pass


REPORT_TYPES = [
    "autorites", "secours", "obstacle_nav", "animal_marin", "pollution", "meteo", "autre",
    # Legacy ids — kept for backward read-compat only.
    "authorities", "obstacle", "fishing_act", "ofni", "fishing_pro", "species",
]


class ReportIn(BaseModel):
    # v2 types per the 27/06/2026 spec (cahier des charges).
    type: Literal["autorites", "secours", "obstacle_nav", "animal_marin", "pollution", "meteo", "autre"]
    lat: float
    lng: float
    description: str = Field(default="", max_length=400)
    photos: List[str] = Field(default_factory=list)  # base64 strings
    heading: Optional[float] = None
    speed_knots: Optional[float] = None
    # Free-form subtype id (per REPORT_TYPES.subtypes in report-types.ts).
    subtype: Optional[str] = None
    # Extra payload collected via subtype.extras (health state, species id,
    # roche variant, pollution level, etc.). Free-form dict to stay forward-
    # compatible with subtype changes without a schema bump.
    extras: Optional[dict] = None
    activity: Optional[Literal["navigation", "control", "stationary", "operation"]] = None


class AvatarIn(BaseModel):
    image: str  # base64 (with or without data URI prefix)


class LocationIn(BaseModel):
    lat: float
    lng: float


class PreferencesIn(BaseModel):
    # Phase K.11 — radius extended from [1..50] to [0.5..500] km so users
    # can fine-tune from a marina-scale bubble up to an entire coastal region.
    # Reports.py clamps to the same range when computing push proximity.
    notify_radius_km: Optional[float] = Field(default=None, ge=0.5, le=500)
    muted_types: Optional[List[str]] = None
    # 13/07/2026 — position des boutons zoom déplaçables sur la carte
    # (offsets tx/ty en px depuis l'ancre par défaut, persistés par compte).
    zoom_btn_pos: Optional[dict] = None


class RegisterPushIn(BaseModel):
    user_id: str
    platform: str  # "android" | "ios"
    device_token: str


class ReportEditIn(BaseModel):
    kind: Literal["fake", "ended", "shift"]
    new_lat: Optional[float] = None
    new_lng: Optional[float] = None
    comment: str = Field(default="", max_length=240)


class ReportEditVoteIn(BaseModel):
    vote: Literal["up", "down"]


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)


class AuthorEditIn(BaseModel):
    """Direct edit by the report's author or a trusted user.

    Author can change `new_lat/new_lng` (position shift) + `status` + `heading`.
    Non-author with reliability ≥ HEADING_EDIT_RELIABILITY_THRESHOLD can change
    ONLY `heading` (for autorites / drift-eligible types).
    """
    new_lat: Optional[float] = None
    new_lng: Optional[float] = None
    status: Optional[Literal["active", "ended"]] = None
    heading: Optional[float] = Field(default=None, ge=0, le=360)
    # 13/07/2026 — vitesse estimée (nds) saisie avec le cap : bascule les
    # autorités/secours stationnaires en « navigation » avec projection.
    speed_knots: Optional[float] = Field(default=None, ge=0, le=99)


# ----------------------------- AUTH endpoints -------------------------------
# Moved out to ``routers/auth.py`` as part of the Phase E.4 refactor.
# The actual endpoints (register, login, google/session, me, patch_me, logout,
# register-push) are defined in that module and included at the bottom of
# this file via ``api.include_router(...)`` so the URLs are identical.


# ----------------------------- REPORTS --------------------------------------
def serialize_edit(e: dict, current_uid: Optional[str] = None) -> dict:
    ups = e.get("upvotes", [])
    downs = e.get("downvotes", [])
    return {
        "id": e["id"],
        "kind": e["kind"],
        "new_lat": e.get("new_lat"),
        "new_lng": e.get("new_lng"),
        "comment": e.get("comment", ""),
        "proposer": {"user_id": e["proposer_id"], "name": e.get("proposer_name", "")},
        "created_at": e["created_at"],
        "up_count": len(ups),
        "down_count": len(downs),
        "net": len(ups) - len(downs),
        "my_vote": ("up" if current_uid in ups else "down" if current_uid in downs else None),
        "applied": bool(e.get("applied")),
        "applied_at": e.get("applied_at"),
    }


def serialize_report(r: dict, current_uid: Optional[str] = None, include_photos: bool = True) -> dict:
    edits = [serialize_edit(e, current_uid) for e in r.get("edits", [])]
    # Author display: ALWAYS the pseudo (never the real name) per spec.
    author_pseudo = (
        r.get("author_pseudo")
        or r.get("author_name")  # legacy fallback for pre-pseudo docs
        or "Marin"
    )
    photos = r.get("photos", []) or []
    # CRITICAL (Phase A.2 OOM fix): the /api/reports list endpoint must NEVER
    # ship the full base64 photo payloads — 30 demo reports × ~1.3 MB photos
    # = 36 MB JSON that OOMs Android JS heap. List responses return only the
    # photo count; the detail endpoint (/api/reports/{id}) returns the full
    # payloads as before.
    return {
        "id": r["id"],
        # ID COURT public (12/07/2026) — affiché sur les posts viraux et
        # cherchable via la loupe de la carte.
        "short_id": r.get("short_id"),
        "type": r["type"],
        "lat": r["lat"],
        "lng": r["lng"],
        "description": r.get("description", ""),
        "photos": photos if include_photos else [],
        "photo_count": len(photos),
        "heading": r.get("heading"),
        "heading_edited_at": r.get("heading_edited_at"),
        "heading_edited_by": r.get("heading_edited_by"),
        "heading_edited_by_name": r.get("heading_edited_by_name"),
        "speed_knots": r.get("speed_knots"),
        "subtype": r.get("subtype"),
        "extras": r.get("extras", {}),
        "activity": r.get("activity"),
        "status": r.get("status", "active"),
        "flagged_fake": bool(r.get("flagged_fake")),
        "is_demo": bool(r.get("is_demo")),
        # Mode test bêta (19/07/2026) : signalement créé par un testeur en
        # mode test — badge « TEST » côté carte et fiche détail.
        "is_test": bool(r.get("is_test")),
        "created_at": r["created_at"],
        "last_confirmed_at": r.get("last_confirmed_at", r["created_at"]),
        "expires_at": r.get("expires_at"),
        "origin_lat": r.get("origin_lat"),
        "origin_lng": r.get("origin_lng"),
        "author_shifted": bool(r.get("author_shifted_at")),
        "confirm_count": len(r.get("confirmations", [])),
        "confirmed_by_me": bool(current_uid and current_uid in r.get("confirmations", [])),
        "author": {
            "user_id": r["author_id"],
            "pseudo": author_pseudo,
            "name": author_pseudo,
            # Phase D — also include the cached snapshot of the author's
            # Marine rank + reliability (resolved by the list/detail handler
            # before serialization). Falls back to defaults when missing.
            "rank_id": r.get("author_rank_id") or "mousse",
            "rank_label": r.get("author_rank_label") or "Mousse",
            "reliability_score": int(r.get("author_reliability") or RELIABILITY_DEFAULT),
        },
        "edits": edits,
        "drift_cone": r.get("drift_cone"),
    }


async def enrich_authors(reports: list[dict]) -> None:
    """Resolve author rank + reliability for every report in-place.
    
    Called by /reports list & detail handlers BEFORE serialization so the
    response payload includes the live author info without bloating storage.
    The fields are written transient on each dict (not persisted), so the
    serializer just reads them.
    """
    if not reports:
        return
    uids = list({r.get("author_id") for r in reports if r.get("author_id")})
    if not uids:
        return
    cursor = db.users.find(
        {"user_id": {"$in": uids}},
        {"_id": 0, "user_id": 1, "points": 1, "reliability_pos": 1, "reliability_neg": 1},
    )
    info: dict[str, dict] = {}
    async for u in cursor:
        rid, rlabel = marine_rank(int(u.get("points", 0)))
        info[u["user_id"]] = {
            "rank_id": rid,
            "rank_label": rlabel,
            "reliability": reliability_score(
                int(u.get("reliability_pos", 0)),
                int(u.get("reliability_neg", 0)),
            ),
        }
    for r in reports:
        meta = info.get(r.get("author_id"))
        if meta:
            r["author_rank_id"] = meta["rank_id"]
            r["author_rank_label"] = meta["rank_label"]
            r["author_reliability"] = meta["reliability"]


# ----- REPORTS + MODERATION -------------------------------------------------
# Endpoints moved to routers/reports.py and routers/moderation.py during the
# Phase E.4 refactor (CRUD reports, confirm, edits, votes, author shifts/delete).


# ----- PROFILE / WEATHER / TTS / DIAGNOSTICS / ROOT --------------------------
# Endpoints moved to routers/profile.py, routers/weather.py, routers/tts.py,
# routers/diagnostics.py during the Phase E.4 refactor.


# ---------------------------------------------------------------------------
# Phase E.4 refactor — sub-routers
# ---------------------------------------------------------------------------
# Routers are imported HERE (after every helper/model/global is defined) so
# their ``import server as srv`` resolves to a fully-initialised module.
# Each sub-router declares its own paths (e.g. ``/auth/login``) and we mount
# them under ``api`` (prefix ``/api``) — so URLs stay identical.
from routers.auth import router as _auth_router  # noqa: E402
from routers.reports import router as _reports_router  # noqa: E402
from routers.moderation import router as _moderation_router  # noqa: E402
from routers.chat import router as _chat_router  # noqa: E402
from routers.profile import router as _profile_router  # noqa: E402
from routers.weather import router as _weather_router  # noqa: E402
from routers.tts import router as _tts_router  # noqa: E402
from routers.diagnostics import router as _diagnostics_router  # noqa: E402
from routers.friends import router as _friends_router  # noqa: E402
from routers.notifications import router as _notifications_router  # noqa: E402
from routers.groups import (  # noqa: E402
    router as _groups_router,
    ensure_indexes as _ensure_group_indexes,
)
from routers.contacts import (  # noqa: E402
    router as _contacts_router,
    ensure_indexes as _ensure_contacts_indexes,
    backfill_phone_hashes as _backfill_phone_hashes,
)
from routers.referral_invites import (  # noqa: E402
    router as _referral_invites_router,
    ensure_indexes as _ensure_referral_invites_indexes,
)
from routers.dev_switch import (  # noqa: E402
    router as _dev_switch_router,
    seed_test_accounts as _seed_test_accounts,
)
from routers.app_version import router as _app_version_router  # noqa: E402
from routers.beta import router as _beta_router  # noqa: E402
from routers.bathy import router as _bathy_router  # noqa: E402
from routers.routing import router as _routing_router  # noqa: E402
from routers.routing_engines import router as _routing_engines_router  # noqa: E402
from routers.support import router as _support_router  # noqa: E402
from routers.tides import router as _tides_router  # noqa: E402
from routers.tiles import router as _tiles_router  # noqa: E402

api.include_router(_auth_router)
api.include_router(_reports_router)
api.include_router(_moderation_router)
api.include_router(_chat_router)
api.include_router(_profile_router)
api.include_router(_weather_router)
api.include_router(_tts_router)
api.include_router(_diagnostics_router)
api.include_router(_friends_router)
api.include_router(_notifications_router)
api.include_router(_groups_router)
api.include_router(_contacts_router)
api.include_router(_referral_invites_router)
api.include_router(_dev_switch_router)
api.include_router(_app_version_router)
api.include_router(_beta_router)
api.include_router(_bathy_router)
api.include_router(_routing_router)
api.include_router(_routing_engines_router)
api.include_router(_support_router)
api.include_router(_tides_router)
api.include_router(_tiles_router)


# ── One-off static hand-off: the "session synthesis" PDF. Served under
# /api/... so it flows through the same Kubernetes ingress that already
# routes to port 8001 (no separate static server needed). Direct GET,
# no auth — this is a shareable link the user requested. ──
_PUBLIC_DIR = ROOT_DIR / "public"


@api.get("/docs/synthese-2026-07-07.pdf", include_in_schema=False)
async def synthese_pdf_download():
    """Return the July 7 session synthesis PDF as an attachment."""
    fp = _PUBLIC_DIR / "synthese-2026-07-07.pdf"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="synthesis_not_found")
    return FileResponse(
        path=str(fp),
        media_type="application/pdf",
        filename="SignalMar_Synthese_2026-07-07.pdf",
        headers={
            "Content-Disposition":
                'attachment; filename="SignalMar_Synthese_2026-07-07.pdf"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@api.get("/docs/synthese-2026-07-08.pdf", include_in_schema=False)
async def synthese_pdf_j2_download():
    """Return the July 8 session synthesis PDF as an attachment."""
    fp = _PUBLIC_DIR / "synthese-2026-07-08.pdf"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="synthesis_not_found")
    return FileResponse(
        path=str(fp),
        media_type="application/pdf",
        filename="SignalMar_Synthese_2026-07-08.pdf",
        headers={
            "Content-Disposition":
                'attachment; filename="SignalMar_Synthese_2026-07-08.pdf"',
            "Cache-Control": "public, max-age=3600",
        },
    )

@api.get("/docs/synthese-2026-07-11.pdf", include_in_schema=False)
async def synthese_pdf_j3_download():
    """Return the July 11 session synthesis PDF as an attachment."""
    fp = _PUBLIC_DIR / "synthese-2026-07-11.pdf"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="synthesis_not_found")
    return FileResponse(
        path=str(fp),
        media_type="application/pdf",
        filename="SignalMar_Synthese_2026-07-11.pdf",
        headers={
            "Content-Disposition":
                'attachment; filename="SignalMar_Synthese_2026-07-11.pdf"',
            "Cache-Control": "public, max-age=3600",
        },
    )

app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Phase 3a — public referral landing page (no /api prefix so it can be
# hit directly from a SMS/WhatsApp/etc. link without the Kubernetes ingress
# rewriting the URL to the API).
# The live demo-map snippets are plain (non f-string) constants so their
# CSS/JS braces don't need escaping inside the landing f-string below.
_JOIN_MAP_CSS = """
  #demo-map{width:100%;height:250px;border-radius:14px;border:1px solid #23324F;margin:14px 0 8px;overflow:hidden;position:relative;z-index:0;background:#0B132B}
  #demo-map .leaflet-tile{filter:brightness(.78) contrast(1.05) saturate(.92)}
  #demo-map .leaflet-container{background:#0B132B}
  .map-cap{font-size:11px;color:#7C8AA8;margin:0 0 14px;line-height:1.5}
  .sm-dot{display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;border:2px solid #0B132B;box-shadow:0 3px 8px rgba(0,0,0,.5);font-size:13px;line-height:1}
"""
_JOIN_MAP_HTML = """
    <div id="demo-map"></div>
    <p class="map-cap">Aperçu en direct — signalements de la communauté entre le Golfe du Morbihan et Belle-Île.</p>
"""
_JOIN_MAP_SCRIPT = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
(function(){
  try {
    var el = document.getElementById('demo-map');
    if (!el || typeof L === 'undefined') return;
    var map = L.map('demo-map', {zoomControl:true, attributionControl:false, scrollWheelZoom:false});
    map.setView([47.46, -2.97], 9);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19}).addTo(map);
    L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', {maxZoom:18, opacity:.9}).addTo(map);
    var COLORS = {autorites:'#48CAE4', secours:'#FF6B6B', obstacle_nav:'#F4A261', animal_marin:'#2A9D8F', pollution:'#9D4CDD', meteo:'#5C7CFA', autre:'#6C757D'};
    var ICONS = {autorites:'\\uD83D\\uDEE1', secours:'\\uD83D\\uDEDF', obstacle_nav:'\\u26A0', animal_marin:'\\uD83D\\uDC2C', pollution:'\\uD83D\\uDEE2', meteo:'\\u26C8', autre:'\\u2049'};
    fetch('/api/reports').then(function(r){ return r.json(); }).then(function(items){
      if (!Array.isArray(items) || !items.length) return;
      var latlngs = [];
      items.slice(0, 60).forEach(function(it){
        var color = COLORS[it.type] || '#48CAE4';
        var icon = ICONS[it.type] || '?';
        var html = '<div class="sm-dot" style="background:' + color + '">' + icon + '</div>';
        L.marker([it.lat, it.lng], {
          icon: L.divIcon({className:'', html: html, iconSize:[26,26], iconAnchor:[13,13]}),
          interactive: false,
        }).addTo(map);
        latlngs.push([it.lat, it.lng]);
      });
      if (latlngs.length) map.fitBounds(L.latLngBounds(latlngs).pad(0.12), {maxZoom: 11});
    }).catch(function(){});
  } catch(_){}
})();
</script>
"""


@app.get("/join", response_class=HTMLResponse)
@app.get("/api/join", response_class=HTMLResponse)
async def referral_landing(ref: str = ""):
    """Detect the visitor's OS and redirect to the right store, while showing
    a friendly fallback screen with the referral code for manual entry."""
    from core.referral import resolve_referrer
    code = (ref or "").strip().upper()[:16]
    friend = await resolve_referrer(db, code) if code else None
    friend_name = (friend or {}).get("pseudo") or (friend or {}).get("name") or ""
    valid = bool(friend)
    safe_code = html.escape(code)
    safe_friend = html.escape(friend_name)
    banner = (
        f"<p class='by'>Invité par <strong>{safe_friend}</strong></p>"
        if valid else
        "<p class='by warn'>Code inconnu — vous pouvez quand même installer l'app.</p>"
    )
    # Simple UA-based store redirect + fallback text with the code for manual
    # entry once the app is installed. We inline everything for zero extra
    # requests (no assets to serve from this pod).
    return f"""<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rejoignez SignalMar</title>
<style>
  :root{{color-scheme:dark}}
  body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#0B132B;color:#E4ECF7;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px;text-align:center}}
  .card{{max-width:420px;width:100%;background:#12203E;border:1px solid #23324F;border-radius:20px;padding:28px 22px;box-shadow:0 12px 40px rgba(0,0,0,0.4)}}
  h1{{font-size:26px;margin:0 0 6px;letter-spacing:.4px;color:#48CAE4}}
  h2{{font-size:14px;font-weight:600;color:#9AA9C5;margin:0 0 20px}}
  .code{{font-family:'SF Mono',Menlo,monospace;font-size:34px;font-weight:900;letter-spacing:6px;background:#0B132B;border:2px dashed #48CAE4;color:#48CAE4;padding:14px 10px;border-radius:12px;margin:14px 0 22px}}
  .btn{{display:inline-flex;align-items:center;gap:8px;background:#48CAE4;color:#0B132B;font-weight:800;padding:14px 22px;border-radius:14px;text-decoration:none;font-size:15px;margin:6px 0}}
  .btn.dark{{background:#23324F;color:#E4ECF7}}
  .by{{font-size:14px;margin:0 0 12px;color:#B7C4DD}}
  .by.warn{{color:#FFD166}}
  .hint{{font-size:12px;color:#7C8AA8;margin-top:22px;line-height:1.6}}
  .btns{{display:flex;flex-direction:column;gap:10px;margin-top:8px}}
{_JOIN_MAP_CSS}
</style>
<script>
  window.addEventListener('DOMContentLoaded', function(){{
    var ua = navigator.userAgent || '';
    var isiOS = /iPhone|iPad|iPod/i.test(ua);
    var isAndroid = /Android/i.test(ua);
    if (isiOS) document.getElementById('cta-ios').style.display='inline-flex';
    else if (isAndroid) document.getElementById('cta-and').style.display='inline-flex';
    else {{
      document.getElementById('cta-ios').style.display='inline-flex';
      document.getElementById('cta-and').style.display='inline-flex';
    }}
  }});
</script>
</head><body>
  <div class="card">
    <h1>⚓ Bienvenue à bord</h1>
    <h2>SignalMar — la communauté maritime</h2>
    {banner}
    <div class="code">{safe_code or '——————'}</div>
{_JOIN_MAP_HTML}
    <p style="font-size:13px;color:#B7C4DD;margin:0 0 14px">
      Utilisez ce code lors de votre inscription pour rejoindre votre ami sur SignalMar.
    </p>
    <div class="btns">
      <a id="cta-ios" href="https://apps.apple.com/app/signalmar" class="btn" style="display:none">
        Télécharger sur l'App Store
      </a>
      <a id="cta-and" href="https://play.google.com/store/apps/details?id=com.emergent.signmarwazemer.sa5b3v" class="btn dark" style="display:none">
        Télécharger sur Google Play
      </a>
    </div>
    <p class="hint">
      À l'ouverture de l'app, entrez le code <strong>{safe_code or 'ci-dessus'}</strong> dans le champ « Code parrain » de l'écran d'inscription.
    </p>
  </div>
{_JOIN_MAP_SCRIPT}
</body></html>"""


@app.on_event("startup")
async def on_startup():
    # Phase A (OTP) — l'email devient OPTIONNEL (comptes créés par téléphone).
    # L'index unique historique indexait aussi les documents sans email
    # (null) → E11000 dès le 2ᵉ compte téléphone. Migration one-shot vers un
    # index unique PARTIEL (uniquement quand email est une string).
    try:
        info = await db.users.index_information()
        legacy = info.get("email_1")
        if legacy and "partialFilterExpression" not in legacy:
            await db.users.drop_index("email_1")
        await db.users.create_index(
            "email", unique=True,
            partialFilterExpression={"email": {"$type": "string"}},
        )
    except Exception:
        pass
    await db.users.create_index("user_id", unique=True)
    # OTP téléphone — TTL auto sur les codes expirés + unicité par numéro.
    try:
        await db.otp_codes.create_index("phone", unique=True)
        await db.otp_codes.create_index("expires_at", expireAfterSeconds=600)
    except Exception:
        pass
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("user_id")
    try:
        await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    except Exception:
        pass
    await db.reports.create_index("id", unique=True)
    await db.reports.create_index([("created_at", -1)])
    await db.report_messages.create_index("report_id")
    # V1.2 — Phase 2 gamification: dedicated history collection.
    try:
        await db.points_history.create_index([("user_id", 1), ("ts", -1)])
    except Exception:
        pass
    # Phase 3a — referral system: unique index + reverse lookup for friends.
    try:
        await db.users.create_index("referral_code", unique=True, sparse=True)
        await db.users.create_index("referred_by", sparse=True)
    except Exception:
        pass
    # Phase 3b — friend requests: fast lookup by (to, status) + (from, status).
    try:
        await db.friend_requests.create_index([("to_user_id", 1), ("status", 1)])
        await db.friend_requests.create_index([("from_user_id", 1), ("status", 1)])
    except Exception:
        pass
    # Phase 3c — in-app notifications: per-user timeline + unread lookup.
    try:
        await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
        await db.notifications.create_index([("user_id", 1), ("read_at", 1)])
    except Exception:
        pass
    # P0 — geo-indexed proximity fan-out: 2dsphere on users.last_loc +
    # one-shot backfill so existing users with only the legacy scalar
    # last_lat/last_lng pair are immediately reachable.
    try:
        from core import notifications as NOTIF
        await NOTIF.ensure_geo_indexes(db)
    except Exception:
        logger.exception("geo notifications index setup failed")
    # Phase E.6 — Météo-France wind cache. TTL slightly above the 30-min
    # freshness cutoff so stale docs get pruned automatically.
    try:
        await db.wind_cache.create_index(
            "fetched_at", expireAfterSeconds=45 * 60
        )
    except Exception:
        pass
    # Phase 4.1 — Private groups indexes.
    try:
        await _ensure_group_indexes(db)
    except Exception:
        logger.exception("groups index setup failed")
    # Phase 4.2 — Contact sync: sparse index on phone_hash + idempotent
    # backfill so users who signed up before the feature can still be
    # matched by their contacts (no data loss).
    try:
        await _ensure_contacts_indexes(db)
        backfilled = await _backfill_phone_hashes(db)
        if backfilled:
            logger.info("phone_hash backfill: %d users", backfilled)
    except Exception:
        logger.exception("contacts index/backfill setup failed")

    # Phase T — Test-account switcher: seed / heal the QA whitelist so
    # every listed account exists with the correct pseudo, phone and
    # shared test password.  Idempotent — safe to run on every boot.
    try:
        report = await _seed_test_accounts(db)
        logger.info("test-account seed: %s", report)
    except Exception:
        logger.exception("test-account seed failed")

    # Phase B — Subscription / viral referral indexes.
    try:
        from core import subscription as SUB
        await SUB.ensure_indexes(db)
    except Exception:
        logger.exception("subscription index setup failed")

    # 31/07/2026 — ID PUBLIC de route + support armateur : indices.
    # 10/09/2026 (contrôle pré-publication) — AUCUNE suppression automatique
    # en base : les index TTL Mongo (computed_routes 30 j, support_screenshots
    # 60 j) sont SUPPRIMÉS (drop idempotent des anciens index TTL s'ils
    # existent d'un déploiement précédent). La rétention devient purement
    # informative (champ created_at) ; les données sont conservées.
    try:
        for _coll, _ttl_idx in (
            (db.computed_routes, "created_at_1"),
            (db.support_screenshots, "created_at_1"),
            (db.reports, "expires_at_ttl"),
        ):
            try:
                await _coll.drop_index(_ttl_idx)
            except Exception:
                pass  # index absent — rien à faire
        await db.computed_routes.create_index("route_id", unique=True)
        await db.computed_routes.create_index([("created_at", -1)])
        await db.support_screenshots.create_index("id", unique=True)
        await db.support_screenshots.create_index([("created_at", -1)])
    except Exception:
        logger.exception("support/computed_routes index setup failed")

    # 01/08/2026 — Moteurs de routage (multi-engine A/B/…) : indices +
    # seed idempotent des built-in (Moteur A et Moteur B, clones stricts).
    try:
        from core import routing_engines as _RE
        await _RE.ensure_indexes(db)
        await _RE.ensure_seed(db)
    except Exception:
        logger.exception("routing_engines seed/index setup failed")
    # Background cleanup task — purges archived reports every hour.
    import asyncio
    app.state.archive_task = asyncio.create_task(_archive_loop())
    # 22/07/2026 — Backup quotidien MongoDB (demande user). Le cron système
    # ne persiste pas aux redémarrages du pod : la planification vit donc ici.
    app.state.backup_task = asyncio.create_task(_backup_loop())
    # 14/07/2026 — pré-génération TTS DÉSACTIVÉE : l'audio des alertes a été
    # retiré de l'app (décision armateur). Le routeur tts.py et la collection
    # tts_cache restent en place, inactifs (réactivables sans refaire le
    # travail) : `pregenerate_alert_catalog()` dans routers/tts.py.
    logger.info("SignMar API ready")


async def _archive_loop():
    """Rétention des signalements SANS AUCUNE suppression en base (10/09/2026,
    exigence du contrôle pré-publication) : la boucle POSE ``expires_at`` sur
    les signalements hérités sans TTL glissant (non confirmés, plus vieux que
    REPORT_TTL_HOURS) — ``update_many`` uniquement, jamais de ``delete`` ni
    d'index TTL. Les lectures (routers/reports.py) filtrent déjà sur
    ``expires_at`` : un signalement expiré disparaît de la carte mais le
    document est CONSERVÉ. Tourne toutes les 10 minutes.
    """
    import asyncio
    while True:
        try:
            now = now_utc()
            cutoff = now - timedelta(hours=REPORT_TTL_HOURS)
            res = await db.reports.update_many(
                {
                    "created_at": {"$lt": cutoff},
                    "expires_at": {"$exists": False},
                    "$or": [{"confirmations": {"$exists": False}}, {"confirmations": {"$size": 0}}],
                },
                {"$set": {"expires_at": now}},
            )
            if res.modified_count:
                logger.info("auto-archived %d legacy reports (purge déléguée au TTL Mongo)",
                            res.modified_count)
        except Exception as e:
            logger.warning("archive loop error: %s", e)
        # Rétention 12 h des captures vidéo envoyées au support (13/07/2026).
        try:
            from routers.diagnostics import purge_expired_support_uploads
            purged = await purge_expired_support_uploads()
            if purged:
                logger.info("purged %d support uploads (>12h)", purged)
        except Exception as e:
            logger.warning("support upload purge error: %s", e)
        await asyncio.sleep(600)


async def _backup_loop():
    """Backup quotidien de la base : lance scripts/backup_db.sh (mongodump
    horodaté + tar.gz dans /app/backups, rotation 7 jours). Un dump est fait
    au démarrage si le dernier date de plus de 24 h, puis contrôle horaire.
    """
    import asyncio
    from pathlib import Path
    script = Path(__file__).parent / "scripts" / "backup_db.sh"
    backups = Path("/app/backups")
    while True:
        try:
            dumps = sorted(backups.glob("mongo_*.tar.gz"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            age_h = ((now_utc().timestamp() - dumps[0].stat().st_mtime) / 3600
                     if dumps else 1e9)
            if age_h >= 24:
                proc = await asyncio.create_subprocess_exec("bash", str(script))
                rc = await proc.wait()
                logger.info("daily mongo backup %s (rc=%d)",
                            "OK" if rc == 0 else "FAILED", rc)
        except Exception as e:
            logger.warning("backup loop error: %s", e)
        await asyncio.sleep(3600)


@app.on_event("shutdown")
async def on_shutdown():
    task = getattr(app.state, "archive_task", None)
    if task:
        task.cancel()
    btask = getattr(app.state, "backup_task", None)
    if btask:
        btask.cancel()
    try:
        await _push_client.aclose()
    except Exception:
        pass
    client.close()
