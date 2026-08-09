"""Reports CRUD + confirmation + author edit + author delete.

Endpoints (mounted under /api):
- POST   /api/reports                  → create a report (geofencing, drift cone, proximity push)
- GET    /api/reports                  → list (radius/types/min_age filters, demo-mode)
- GET    /api/reports/{rid}            → single report (with photos)
- POST   /api/reports/{rid}/confirm    → community confirmation (TTL slide, +rel, push)
- PATCH  /api/reports/{rid}            → author or trusted-user edit (heading override, position shift, status)
- DELETE /api/reports/{rid}            → author deletion (1/week quota, dev bypass)

All heavy lifting lives in ``server`` (helpers, drift_calc, models). This
router purely re-locates HTTP handlers.
"""
from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request

import server as srv
from core import notifications as NOTIF

router = APIRouter(tags=["reports"])


# Human-readable labels for proximity push titles. Kept module-level so the
# BackgroundTask closure doesn't rebuild the dict on every report.
_REPORT_TYPE_LABELS: dict[str, str] = {
    # v2 ids (cahier des charges 27/06/2026)
    "autorites": "Autorités",
    "secours": "Secours en mer",
    "obstacle_nav": "Obstacle à la navigation",
    "animal_marin": "Animal marin",
    "pollution": "Pollution",
    "autre": "Signalement",
    # legacy ids — kept for graceful fallback while old docs exist.
    "authorities": "Autorités",
    "obstacle": "Obstacle",
    "fishing_act": "Animal marin",
    "ofni": "OFNI",
    "fishing_pro": "Pêche pro",
    "species": "Espèce protégée",
}


# ── ID court public (12/07/2026) ────────────────────────────────────────────
# 8 caractères MAJUSCULES sans ambiguïté (pas de I/L/O/0/1) → lisible sur un
# post et dictable à la VHF. Unicité garantie par index + re-tirage.
_SHORT_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


async def _new_short_id() -> str:
    import secrets
    for _ in range(6):
        code = "".join(secrets.choice(_SHORT_ALPHABET) for _ in range(8))
        if not await srv.db.reports.find_one({"short_id": code}, {"_id": 1}):
            return code
    raise HTTPException(status_code=500, detail="short_id_generation_failed")


async def ensure_short_id(r: dict) -> dict:
    """Backfill paresseux : les signalements créés avant le 12/07 n'ont pas
    de short_id — on en génère un à la première lecture détail."""
    if not r.get("short_id"):
        code = await _new_short_id()
        await srv.db.reports.update_one({"id": r["id"]}, {"$set": {"short_id": code}})
        r["short_id"] = code
    return r


@router.get("/reports/by-code/{code}")
async def report_by_code(code: str, request: Request):
    """Recherche par ID COURT (loupe de la carte). Renvoie l'id long."""
    await srv.current_user(request)
    c = (code or "").strip().upper()
    if not (4 <= len(c) <= 12):
        raise HTTPException(status_code=422, detail="code_invalide")
    r = await srv.db.reports.find_one({"short_id": c}, {"_id": 0, "id": 1, "short_id": 1, "type": 1})
    if not r:
        raise HTTPException(status_code=404, detail="Aucun signalement avec ce code.")
    return r


@router.get("/public/report/{code}")
async def public_report_preview(code: str):
    """Aperçu PUBLIC (sans auth) d'un signalement via son ID COURT.

    Alimente la page web publique /s/[CODE] partagée sur les posts viraux.
    Règles produit : position APPROXIMATIVE uniquement (arrondie 0,1°),
    extrait de 100 caractères, pseudo de l'auteur (jamais le vrai nom).
    """
    c = (code or "").strip().upper()
    if not (4 <= len(c) <= 12):
        raise HTTPException(status_code=422, detail="code_invalide")
    r = await srv.db.reports.find_one({"short_id": c}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Aucun signalement avec ce code.")
    desc = (r.get("description") or "").strip()
    excerpt = desc[:100].rstrip() + "..." if len(desc) > 100 else desc
    exp = r.get("expires_at")
    expired = exp is not None and srv.ensure_aware(exp) <= srv.now_utc()
    status = "ended" if r.get("status") == "ended" else ("expired" if expired else "active")
    photos = r.get("photos") or []
    return {
        "short_id": r.get("short_id"),
        "type": r["type"],
        "subtype": r.get("subtype"),
        "approx_lat": round(float(r["lat"]), 1),
        "approx_lng": round(float(r["lng"]), 1),
        "description_excerpt": excerpt,
        "created_at": r["created_at"],
        "confirm_count": len(r.get("confirmations", [])),
        "author_pseudo": r.get("author_pseudo") or r.get("author_name") or "Marin",
        "status": status,
        "photo": photos[0] if photos else None,
    }


@router.post("/reports")
async def create_report(
    body: "srv.ReportIn",
    request: Request,
    background_tasks: BackgroundTasks,
):
    u = await srv.current_user(request)
    rid = srv.new_id()
    short_id = await _new_short_id()
    # Mode test bêta (19/07/2026) : testeur déclaré + toggle ON → création
    # autorisée depuis la terre, signalement marqué is_test (badge TEST).
    from routers import beta as BETA
    test_mode_on = await BETA.test_mode_active(u)
    # Phase 2: geofencing — point must be at sea (≥ ~1 km from coast).
    # Dev bypass: maintainer accounts can create from anywhere for testing.
    if not srv.is_dev_user(u) and not test_mode_on \
            and not await srv.is_at_sea(body.lat, body.lng):
        raise HTTPException(
            status_code=422,
            detail="Création interdite hors de la mer (≥ 1 km de la côte requis).",
        )

    doc = {
        "id": rid,
        # ID COURT public (12/07/2026) : 8 caractères non ambigus, MAJUSCULES,
        # affiché sur les posts « viraux » et cherchable via la loupe carte.
        "short_id": short_id,
        "type": body.type,
        "lat": body.lat,
        "lng": body.lng,
        # Origin coords are frozen so the 1 km author-edit radius is computed
        # against the *initial* point even after a shift.
        "origin_lat": body.lat,
        "origin_lng": body.lng,
        "description": body.description,
        "photos": body.photos[:3],
        "heading": body.heading,
        "speed_knots": body.speed_knots,
        "subtype": body.subtype,
        # Phase A v2: extras carries subtype-specific context (health state,
        # animal species, roche variant, pollution level, etc.).
        "extras": body.extras or {},
        "activity": body.activity,
        "author_id": u["user_id"],
        # Pseudonymised display name (Phase A v2: never expose real name).
        "author_pseudo": u.get("pseudo") or u.get("name", "Marin"),
        "author_name": u.get("name", ""),  # kept internally for audit
        "created_at": srv.now_utc(),
        "last_confirmed_at": srv.now_utc(),
        # Sliding lifetime — per cahier des charges, depends on type/subtype.
        "expires_at": srv.now_utc() + timedelta(
            minutes=srv.effective_ttl_minutes(body.type, body.subtype)
        ),
        "confirmations": [],
    }
    if test_mode_on:
        doc["is_test"] = True
    await srv.db.reports.insert_one(doc)
    # V1.2 — Phase 2 gamification: first report = +10, subsequent = +5, and
    # the delta is written to the points_history journal for the profile page.
    from core import points as PT
    fresh_u = await srv.db.users.find_one(
        {"user_id": u["user_id"]},
        {"_id": 0, "first_report_bonus_given": 1},
    ) or {}
    is_first = not bool(fresh_u.get("first_report_bonus_given"))
    if is_first:
        awarded_pts = PT.POINTS_FIRST_REPORT
        await PT.award_points(
            srv.db, u["user_id"], awarded_pts,
            PT.REASON_FIRST_REPORT, report_id=rid,
        )
        await srv.db.users.update_one(
            {"user_id": u["user_id"]},
            {"$set": {"first_report_bonus_given": True}},
        )
        # Phase B — subscription bonus flow: mark the pending referral
        # as awaiting external confirmation. Idempotent; only fires
        # on the user's very first report (first_report_bonus_given
        # gate guarantees single-shot).
        try:
            from core import subscription as SUB
            await SUB.on_first_report(srv.db, u["user_id"], rid)
        except Exception as e:
            srv.logger.warning("subscription.on_first_report failed: %s", e)
    else:
        awarded_pts = PT.POINTS_REPORT
        await PT.award_points(
            srv.db, u["user_id"], awarded_pts,
            PT.REASON_REPORT, report_id=rid,
        )

    # Phase B — drift cone: compute & persist on creation for eligible
    # subtypes. Best-effort (Open-Meteo can fail) — never blocks the response.
    # Phase E.3 — if the user-set heading is present at creation, the cone is
    # oriented along it (override of the algorithmic bearing).
    try:
        cone = await srv.refresh_drift_cone(
            rid, body.lat, body.lng, body.type,
            body.subtype, body.extras,
            heading=body.heading,
        )
        if cone:
            doc["drift_cone"] = cone
    except Exception as e:
        srv.logger.warning("drift_cone (create) failed: %s", e)

    # Proximity push: geo-indexed fan-out queued as a BackgroundTask so the
    # HTTP response returns immediately. Scales to 500 k users (2dsphere
    # index on ``users.last_loc`` + centerSphere spatial query — see
    # ``core/notifications.py::dispatch_proximity_push``).
    try:
        label = _REPORT_TYPE_LABELS.get(body.type, "Signalement")
        background_tasks.add_task(
            NOTIF.dispatch_proximity_push,
            srv.db,
            srv.send_push,
            lat=body.lat,
            lng=body.lng,
            exclude_user_id=u["user_id"],
            report_type=body.type,
            title=f"{label} à proximité",
            message="Un nouveau signalement vient d'apparaître près de vous.",
            action_url=f"/report/{rid}",
            idempotency_key=f"new-report:{rid}",
        )
    except Exception as e:
        srv.logger.warning("proximity push queue failed: %s", e)

    result = srv.serialize_report(doc, u["user_id"])
    # Expose the awarded points so the client can show a rich confirmation
    # toast ("+10 pts — 1er signalement" / "+5 pts").
    result["points_awarded"] = int(awarded_pts)
    result["is_first_report"] = bool(is_first)
    return result


@router.get("/reports")
async def list_reports(request: Request, lat: Optional[float] = None,
                       lng: Optional[float] = None, radius_km: float = 500,
                       min_age_hours: Optional[float] = None,
                       types: Optional[str] = None):
    """List reports.

    - When **unauthenticated** (demo mode), `min_age_hours` is forced to >= 12
      so anonymous users only see older reports.
    - `types` is a comma-separated list of allowed report types.
    """
    u = None
    try:
        u = await srv.current_user(request)
    except HTTPException:
        pass

    # Demo mode: hide live reports — only show reports older than 12h.
    if u is None:
        if min_age_hours is None or min_age_hours < 12:
            min_age_hours = 12

    allowed_types = None
    if types:
        allowed_types = {t.strip() for t in types.split(",") if t.strip()}

    cursor = srv.db.reports.find({}, {"_id": 0}).sort("created_at", -1).limit(500)
    kept: list[dict] = []
    cutoff = None
    if min_age_hours is not None:
        cutoff = srv.now_utc() - timedelta(hours=min_age_hours)
    # Auto-archive: unconfirmed reports older than REPORT_TTL_HOURS are hidden.
    archive_cutoff = srv.now_utc() - timedelta(hours=srv.REPORT_TTL_HOURS)
    now = srv.now_utc()
    async for r in cursor:
        if allowed_types and r["type"] not in allowed_types:
            continue
        # Phase 2 sliding-TTL: hide expired reports (1h default, extended on confirm).
        exp = r.get("expires_at")
        if exp is not None and srv.ensure_aware(exp) <= now:
            continue
        # Hide reports the author closed.
        if r.get("status") == "ended":
            continue
        created = srv.ensure_aware(r["created_at"])
        # Hide unconfirmed reports past the archive TTL (legacy fallback for docs
        # without an `expires_at` field, e.g. legacy seed data). Demo reports
        # (`is_demo=True`) are exempt — they rely solely on their far-future
        # `expires_at` so the anonymous demo map stays populated.
        if not r.get("is_demo") and not r.get("confirmations") and created < archive_cutoff:
            continue
        if cutoff is not None and created > cutoff:
            continue
        if lat is not None and lng is not None:
            if srv.haversine_km(lat, lng, r["lat"], r["lng"]) > radius_km:
                continue
        kept.append(r)
    # Phase D — resolve author rank + reliability in a single batch query.
    await srv.enrich_authors(kept)
    return [
        srv.serialize_report(r, u["user_id"] if u else None, include_photos=False)
        for r in kept
    ]


@router.get("/reports/{rid}")
async def get_report(rid: str, request: Request):
    u = None
    try:
        u = await srv.current_user(request)
    except HTTPException:
        pass
    r = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    # Backfill paresseux du short_id pour les signalements pré-12/07.
    r = await ensure_short_id(r)
    await srv.enrich_authors([r])
    return srv.serialize_report(r, u["user_id"] if u else None)


@router.post("/reports/{rid}/deny")
async def deny_report(rid: str, request: Request):
    """Infirmation communautaire « à la Waze » (15/07/2026, GO armateur).

    Déclenchée par la popup de passage à proximité (« Signalement toujours
    là ? » → « Non, pas vu »). Règles validées :
      • N'a d'effet que si l'info est FRAÎCHE : signalement créé < 30 min
        OU dernière confirmation < 30 min. Sinon → aucun effet (le TTL
        naturel fait le ménage).
      • 1 « Non » ne tue jamais un signalement : il RACCOURCIT le TTL
        (expiration ramenée à ≤ 15 min).
      • Retrait uniquement si : signalement < 30 min ET jamais confirmé
        (faux signalement probable), OU ≥ 2 « Non » cumulés.
      • Un « Non » sur son propre signalement est refusé ; 1 seul « Non »
        par utilisateur et par signalement ; aucun point attribué.
    Le retrait = expires_at → maintenant (non destructif, le doc reste).
    """
    u = await srv.current_user(request)
    r = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    if r.get("author_id") == u["user_id"]:
        raise HTTPException(
            status_code=422,
            detail="Vous ne pouvez pas infirmer votre propre signalement.",
        )
    denials = list(r.get("denials", []))
    if u["user_id"] in denials:
        return {"effect": "none", "already": True}
    now = srv.now_utc()
    age_min = (now - srv.ensure_aware(r["created_at"])).total_seconds() / 60
    last_conf = r.get("last_confirmed_at")
    conf_age_min = (
        (now - srv.ensure_aware(last_conf)).total_seconds() / 60
        if last_conf else None
    )
    fresh = age_min < 30 or (conf_age_min is not None and conf_age_min < 30)
    if not fresh:
        # Signalement ancien sans info récente → on ne fait rien (règle user).
        return {"effect": "none"}
    denials.append(u["user_id"])
    updates: dict = {"denials": denials, "last_denied_at": now}
    fresh_unconfirmed = age_min < 30 and not r.get("confirmations")
    if fresh_unconfirmed or len(denials) >= 2:
        # Retrait : expiration immédiate → disparaît des listes/alertes.
        updates["expires_at"] = now
        updates["denied_by_community"] = True
        effect = "removed"
    else:
        # 1er « Non » sur un signalement confirmé → TTL raccourci à ≤ 15 min.
        cur_exp = r.get("expires_at")
        short_exp = now + timedelta(minutes=15)
        if cur_exp is None or srv.ensure_aware(cur_exp) > short_exp:
            updates["expires_at"] = short_exp
        effect = "ttl_reduced"
    await srv.db.reports.update_one({"id": rid}, {"$set": updates})
    srv.logger.info(
        "deny_report %s by %s → %s (denials=%d, age=%.0f min)",
        rid, u["user_id"], effect, len(denials), age_min,
    )
    return {"effect": effect, "denial_count": len(denials)}


@router.post("/reports/{rid}/confirm")
async def confirm_report(rid: str, request: Request, body: Optional[dict] = Body(None)):
    u = await srv.current_user(request)
    r = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    # Phase 2: the confirmer must be at sea (last known location ≤ 24h old).
    # Dev bypass: maintainer accounts skip both checks. Mode test bêta
    # (19/07/2026) : les testeurs en mode test confirment aussi depuis la
    # terre (validation croisée des signalements de test).
    from routers import beta as BETA
    if not srv.is_dev_user(u) and not await BETA.test_mode_active(u):
        fix = srv._ensure_user_at_sea_field(u)
        if fix is None:
            raise HTTPException(
                status_code=422,
                detail="Position GPS récente requise pour confirmer (autorisez la localisation).",
            )
        if not await srv.is_at_sea(fix[0], fix[1]):
            raise HTTPException(
                status_code=422,
                detail="Confirmation interdite depuis la terre — vous devez être en mer.",
            )
    confirmations = r.get("confirmations", [])
    already_confirmed = u["user_id"] in confirmations
    # V1.2 — Phase 2: reject self-confirmation to prevent gamification abuse.
    if not already_confirmed and r.get("author_id") == u["user_id"]:
        raise HTTPException(
            status_code=422,
            detail="Vous ne pouvez pas confirmer votre propre signalement.",
        )
    # Response-level flags describing what actually happened (surfaced to the
    # confirmer's UI so we can show a rich toast — see /new.tsx contract).
    confirmer_points_awarded = 0
    author_reliability_awarded = 0
    referral_bonus_paid = False
    if not already_confirmed:
        confirmations.append(u["user_id"])
        from core import points as PT
        from core import referral as REF
        # 15/07/2026 — confirmation « de passage » (popup proximité) : points
        # réduits de moitié (anti-farming, validé armateur) vs fiche détail.
        proximity = bool(body and body.get("source") == "proximity")
        confirm_points = (
            max(1, PT.POINTS_CONFIRM_OTHER // 2) if proximity
            else PT.POINTS_CONFIRM_OTHER
        )
        # Anti-abuse: enforce daily cap on rewarded confirmations. If the cap
        # is hit the confirmation still lands (visible to the community) but
        # the confirmer does not earn +2 grade points for it.
        if await PT.can_reward_confirmation(srv.db, u["user_id"]):
            await PT.award_points(
                srv.db, u["user_id"], confirm_points,
                PT.REASON_CONFIRM, report_id=rid,
            )
            confirmer_points_awarded = confirm_points
        # Reliability: +3 to the author (not self, already guarded above).
        if r.get("author_id"):
            await PT.award_reliability(
                srv.db, r["author_id"], PT.RELIABILITY_CONFIRM_OTHER,
                PT.REASON_CONFIRM_AUTHOR, report_id=rid,
            )
            author_reliability_awarded = PT.RELIABILITY_CONFIRM_OTHER
            # Phase 3a — referral bonus: +20 grade to the referrer the *first*
            # time this author's report gets confirmed by someone else.
            referral_bonus_paid = await REF.pay_referral_bonus(
                srv.db, r["author_id"], rid,
            )
            # Phase B — Premium bonus month: fires only when the confirmer
            # is external to the referee's private groups (anti-farm gate
            # inside). Idempotent per referee. Fails silently on error so
            # the confirmation flow itself is never broken.
            try:
                from core import subscription as SUB
                await SUB.try_award_bonus(
                    srv.db,
                    report_id=rid,
                    report_author_uid=r["author_id"],
                    confirmer_uid=u["user_id"],
                )
            except Exception as e:
                srv.logger.warning("subscription.try_award_bonus failed: %s", e)
    # Sliding TTL: each confirmation extends the report's lifetime by the
    # type-specific TTL (e.g. 6h for animal_marin, 24h for pollution_cote).
    sliding_ttl = srv.effective_ttl_minutes(r.get("type", ""), r.get("subtype"))
    await srv.db.reports.update_one(
        {"id": rid},
        {"$set": {
            "confirmations": confirmations,
            "last_confirmed_at": srv.now_utc(),
            "expires_at": srv.now_utc() + timedelta(minutes=sliding_ttl),
            # 15/07/2026 — une confirmation (info positive fraîche) efface
            # les « Non, pas vu » accumulés (infirmation communautaire).
            "denials": [],
        }},
    )
    # Phase B — recompute the drift cone on every confirmation so the
    # projected polygon reflects the *current* wind + current vectors.
    # Phase E.3 — preserve any user-set heading override on the cone.
    try:
        await srv.refresh_drift_cone(
            rid, r["lat"], r["lng"], r.get("type"), r.get("subtype"),
            r.get("extras"),
            heading=r.get("heading"),
        )
    except Exception as e:
        srv.logger.warning("drift_cone (confirm) failed: %s", e)
    # Notify the author (non-blocking, never raises).
    if (
        not already_confirmed
        and r.get("author_id")
        and r["author_id"] != u["user_id"]
    ):
        try:
            # Base notif — confirmation reçue + gain de fiabilité.
            msg = (
                f"{u.get('name', 'Un marin')} a confirmé votre signalement — "
                f"+{author_reliability_awarded} % fiabilité."
            )
            await srv.send_push(
                recipients=[r["author_id"]],
                data={
                    "title": "Signalement confirmé",
                    "message": msg,
                    "action_url": f"/report/{rid}",
                },
                idempotency_key=f"confirm:{rid}:{u['user_id']}",
            )
            # If the referral bonus was released, also notify the referrer
            # (a separate title so both notifs are distinguishable).
            if referral_bonus_paid:
                author_doc = await srv.db.users.find_one(
                    {"user_id": r["author_id"]},
                    {"_id": 0, "referrer_user_id": 1, "pseudo": 1, "name": 1},
                ) or {}
                referrer_uid = author_doc.get("referrer_user_id")
                if referrer_uid:
                    friend_label = author_doc.get("pseudo") or author_doc.get("name") or "votre filleul"
                    await srv.send_push(
                        recipients=[referrer_uid],
                        data={
                            "title": "Bonus parrainage",
                            "message": (
                                f"{friend_label} a fait son premier signalement confirmé — "
                                "+20 pts de grade !"
                            ),
                            "action_url": "/profile/friends",
                        },
                        idempotency_key=f"referral:{r['author_id']}",
                    )
        except Exception as e:
            srv.logger.warning("push confirm failed: %s", e)
    r = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    result = srv.serialize_report(r, u["user_id"])
    # V1.2 — surface the deltas so the confirmer's UI can toast the impact.
    author_pseudo = None
    if r.get("author_id"):
        au = await srv.db.users.find_one(
            {"user_id": r["author_id"]},
            {"_id": 0, "pseudo": 1, "name": 1},
        )
        if au:
            author_pseudo = au.get("pseudo") or au.get("name")
    result["confirmer_points_awarded"] = int(confirmer_points_awarded)
    result["author_reliability_awarded"] = int(author_reliability_awarded)
    result["author_pseudo"] = author_pseudo
    result["referral_bonus_paid"] = bool(referral_bonus_paid)
    return result


@router.patch("/reports/{rid}")
async def author_edit_report(
    rid: str, body: "srv.AuthorEditIn", request: Request
):
    """Direct edit by the report's author OR by a trusted user.

    Author can:
    - Shift position once (within AUTHOR_EDIT_MAX_RADIUS_KM km, must stay at sea).
    - Update status (active/ended) without limit.
    - Update heading (cap) without limit.

    Non-author with reliability ≥ HEADING_EDIT_RELIABILITY_THRESHOLD% can:
    - Update heading ONLY (and only on autorites/secours or drift-eligible types).
    """
    u = await srv.current_user(request)
    r = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")

    is_author = r.get("author_id") == u["user_id"]
    user_rel = srv.user_reliability(u)
    is_shift = body.new_lat is not None and body.new_lng is not None
    wants_status = body.status is not None
    wants_heading = body.heading is not None
    # Mode test bêta : un testeur en mode test bénéficie des mêmes
    # assouplissements que les comptes dev sur SON signalement de TEST
    # (déplacement à terre, re-déplacement) — jamais sur un vrai signalement.
    from routers import beta as BETA
    dev = srv.is_dev_user(u) or (
        bool(r.get("is_test")) and await BETA.test_mode_active(u)
    )

    # Only the author can change position or status.
    if (is_shift or wants_status) and not is_author:
        raise HTTPException(
            status_code=403,
            detail="Seul l'auteur peut modifier la position ou clore ce signalement.",
        )

    # Heading editing eligibility: author OR reliable user (≥ threshold).
    if (
        wants_heading
        and not is_author
        and user_rel < srv.HEADING_EDIT_RELIABILITY_THRESHOLD
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Indice de fiabilité ≥ {srv.HEADING_EDIT_RELIABILITY_THRESHOLD}% "
                f"requis pour modifier le cap (actuel : {user_rel}%)."
            ),
        )

    # Heading editing is only meaningful for autorites/secours (cap nav) and
    # drift-eligible types (cap de dérive).
    if wants_heading:
        rtype = r.get("type")
        if rtype not in ("autorites", "secours") and not srv.drift_cone_eligible(
            rtype, r.get("subtype"), r.get("extras")
        ):
            raise HTTPException(
                status_code=422,
                detail="Le cap n'est modifiable que pour les autorités, secours et objets dérivants.",
            )

    update: dict = {}

    if is_shift:
        if not dev and r.get("author_shifted_at"):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Vous avez déjà repositionné ce signalement. "
                    "Supprimez-le et recréez-le pour le déplacer ailleurs."
                ),
            )
        olat = r.get("origin_lat", r.get("lat"))
        olng = r.get("origin_lng", r.get("lng"))
        dkm = srv.haversine_km(olat, olng, body.new_lat, body.new_lng)
        if not dev and dkm > srv.AUTHOR_EDIT_MAX_RADIUS_KM:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Trop loin de la position d'origine ({dkm:.2f} km > "
                    f"{srv.AUTHOR_EDIT_MAX_RADIUS_KM:.1f} km). "
                    "Supprimez et recréez le signalement."
                ),
            )
        if not dev and not await srv.is_at_sea(body.new_lat, body.new_lng):
            raise HTTPException(
                status_code=422,
                detail="La nouvelle position doit être en mer (≥ 1 km de la côte).",
            )
        update["lat"] = body.new_lat
        update["lng"] = body.new_lng
        update["author_shifted_at"] = srv.now_utc()

    if wants_status:
        update["status"] = body.status

    if wants_heading:
        update["heading"] = float(body.heading) % 360.0
        update["heading_edited_at"] = srv.now_utc()
        update["heading_edited_by"] = u["user_id"]
        # Cache the editor's pseudo so the frontend can display
        # "Cap observé par <pseudo>" without an extra user lookup.
        update["heading_edited_by_name"] = (
            u.get("pseudo") or u.get("name") or "Marin"
        )
        # 13/07/2026 — saisir un cap sur une autorité/secours (même
        # stationnaire ou en contrôle) bascule le signalement « En
        # navigation » avec une vitesse estimée (défaut 10 nds si absente) :
        # la flèche de projection apparaît alors sur la carte.
        if r.get("type") in ("autorites", "secours"):
            update["activity"] = "navigation"
            spd = (
                body.speed_knots
                if body.speed_knots is not None
                else (r.get("speed_knots") or 10.0)
            )
            update["speed_knots"] = float(spd)

    if not update:
        raise HTTPException(status_code=400, detail="Aucun changement fourni")

    # Mark as touched by an author edit only when the author is the one editing.
    if is_author:
        update["author_edited_at"] = srv.now_utc()

    await srv.db.reports.update_one({"id": rid}, {"$set": update})
    # Phase B + E.3 — drift cone refresh:
    #  - status=ended → clear the cone (the report is over).
    #  - position shift → recompute from the new coords + fresh wind/current,
    #    keeping any user-set heading override.
    #  - heading change → recompute so the cone now follows the new bearing.
    try:
        if body.status == "ended":
            await srv.db.reports.update_one(
                {"id": rid}, {"$unset": {"drift_cone": ""}}
            )
        elif is_shift or wants_heading:
            new_lat = body.new_lat if is_shift else r["lat"]
            new_lng = body.new_lng if is_shift else r["lng"]
            new_heading = (
                update.get("heading", r.get("heading"))
                if wants_heading
                else r.get("heading")
            )
            await srv.refresh_drift_cone(
                rid, new_lat, new_lng,
                r.get("type"), r.get("subtype"), r.get("extras"),
                heading=new_heading,
            )
    except Exception as e:
        srv.logger.warning("drift_cone (edit) failed: %s", e)
    fresh = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    return srv.serialize_report(fresh, u["user_id"])


@router.delete("/reports/{rid}")
async def delete_report(rid: str, request: Request):
    """Author-only deletion.

    Phase 2: an author may delete at most AUTHOR_DELETE_WEEKLY_LIMIT of
    their own reports per rolling 7-day window. The full delete-timestamp
    history is kept on the user doc for audit (trimmed to last 30 days).
    """
    u = await srv.current_user(request)
    r = await srv.db.reports.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    # 23/07/2026 — MODÉRATION : les comptes dev/admin peuvent supprimer
    # n'importe quel signalement (nettoyage des artefacts de test qui
    # restaient sur la carte : l'auteur-only + quota hebdo bloquaient les
    # nettoyages → marqueurs fantômes sur la terre ferme).
    if r.get("author_id") != u["user_id"] and not srv.is_dev_user(u):
        raise HTTPException(status_code=403, detail="Seul l'auteur peut supprimer")
    # Count deletions within the last 7 days — bypassed for dev accounts.
    week_ago = srv.now_utc() - timedelta(days=7)
    deletions_log: list = u.get("deletions_log") or []
    # Normalise to aware datetimes for comparison.
    recent = [d for d in deletions_log if srv.ensure_aware(d) >= week_ago]
    if not srv.is_dev_user(u) and len(recent) >= srv.AUTHOR_DELETE_WEEKLY_LIMIT:
        # Compute the next slot freeing-up time for a friendly message.
        next_free = srv.ensure_aware(sorted(recent)[0]) + timedelta(days=7)
        raise HTTPException(
            status_code=429,
            detail=(
                "Quota hebdomadaire atteint (1 suppression / 7 jours). "
                f"Prochain créneau disponible : {next_free.strftime('%d/%m %H:%M UTC')}."
            ),
        )
    await srv.db.reports.delete_one({"id": rid})
    await srv.db.report_messages.delete_many({"report_id": rid})
    # Push the deletion timestamp, keep only entries from the last 30 days.
    keep_after = srv.now_utc() - timedelta(days=30)
    new_log = [d for d in deletions_log if srv.ensure_aware(d) >= keep_after]
    new_log.append(srv.now_utc())
    await srv.db.users.update_one(
        {"user_id": u["user_id"]},
        {"$set": {"deletions_log": new_log}},
    )
    return {"ok": True}
