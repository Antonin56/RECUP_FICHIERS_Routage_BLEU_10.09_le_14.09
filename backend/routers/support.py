"""SignalMar — Endpoints support (compte admin uniquement, 31/07/2026).

Reçoit les captures d'écran envoyées depuis la carte par le propriétaire de
l'application pour diagnostiquer un problème de route/carte remonté depuis
le terrain. Endpoints verrouillés sur ``is_signalmar_admin`` (téléphone
armateur — jamais accessibles aux comptes standards).

Persistance : collection ``support_screenshots`` (TTL 60 j, index créé
au démarrage du serveur). L'image est stockée en base64 dans le document
(taille bornée à 4 Mo côté API — la carte Leaflet capturée fait ~200 Ko).
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import server as srv
from core.auth import current_user
from core.support_admin import is_signalmar_admin

logger = logging.getLogger("signalmar.support")
router = APIRouter(prefix="/support", tags=["support"])


# 4 Mo max côté API — la capture WebView Leaflet (JPEG q=0.6) fait
# habituellement 150-400 Ko. Au-delà, on refuse pour éviter les fuites.
_MAX_IMAGE_BYTES = 4 * 1024 * 1024
_ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _new_screenshot_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suf = "".join(secrets.choice(_ID_ALPHABET) for _ in range(3))
    return f"S-{ts}-{suf}"


class ScreenshotIn(BaseModel):
    # Data URL ("data:image/jpeg;base64,...") OU base64 brut.
    # 03/08/2026 — OPTIONNEL : sur le navigateur, react-native-view-shot ne
    # peut pas photographier l'iframe Leaflet (canvas « teinté » par les tuiles
    # tierces). L'app envoie alors le CONTEXTE seul (coordonnées, moteur, tracé
    # complet, avertissements), qui suffit à rejouer le calcul côté serveur.
    image_b64: Optional[str] = Field(None, min_length=32)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    depth_zh_m: Optional[float] = None
    comment: Optional[str] = Field(None, max_length=500)
    route_id: Optional[str] = Field(None, max_length=64)
    # Contexte capté côté app (mode carte, zoom, réglages bateau…).
    context: Optional[dict] = None


class ScreenshotCommitIn(BaseModel):
    """03/08/2026 — finalisation d'une capture envoyée PAR MORCEAUX."""
    upload_id: str = Field(..., min_length=8, max_length=64)
    mime: Optional[str] = Field(None, max_length=40)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    depth_zh_m: Optional[float] = None
    comment: Optional[str] = Field(None, max_length=500)
    route_id: Optional[str] = Field(None, max_length=64)
    context: Optional[dict] = None


@router.post("/screenshot")
async def upload_screenshot(body: ScreenshotIn, user: dict = Depends(current_user)):
    """Reçoit une capture d'écran (map + route + balises) et son contexte.
    Réservé au compte SignalMar admin (armateur)."""
    if not is_signalmar_admin(user):
        raise HTTPException(403, "Fonction réservée au compte SignalMar admin.")

    raw = (body.image_b64 or "").strip() or None
    if raw is not None:
        # Contrôle de taille grossier (base64 ≈ 4/3 des octets décodés).
        if int(len(raw) * 3 / 4) > _MAX_IMAGE_BYTES:
            raise HTTPException(413, "Capture trop volumineuse (max 4 Mo).")
    elif not (body.context or body.lat is not None):
        raise HTTPException(422, "Capture vide : image ou contexte requis.")

    sid = _new_screenshot_id()
    doc = {
        "id": sid,
        "user_id": user.get("user_id"),
        "user_phone": user.get("phone"),
        "created_at": datetime.now(timezone.utc),
        "image_b64": raw,
        "lat": body.lat,
        "lng": body.lng,
        "depth_zh_m": body.depth_zh_m,
        "comment": body.comment,
        "route_id": body.route_id,
        "context": body.context or {},
        "has_image": raw is not None,
    }
    await srv.db.support_screenshots.insert_one(doc)
    logger.info(
        "support screenshot uploaded id=%s user=%s route=%s coords=(%s,%s) image=%s",
        sid, user.get("user_id"), body.route_id, body.lat, body.lng, raw is not None,
    )
    return {"ok": True, "id": sid, "created_at": doc["created_at"].isoformat()}


@router.post("/screenshot/commit")
async def commit_screenshot(body: ScreenshotCommitIn, user: dict = Depends(current_user)):
    """03/08/2026 — Finalise une capture envoyée PAR MORCEAUX.

    L'envoi en un seul POST (~400 Ko de base64) était throttlé par l'ingress :
    l'armateur voyait « support screenshot failed {"status":429} » et la
    capture n'arrivait jamais (dernière capture réellement reçue : 12h28 le
    03/08, aucune ensuite). L'app découpe désormais l'image en morceaux de
    ~128 Ko via /api/support/upload/chunk, puis appelle cet endpoint qui
    assemble le fichier et crée le document `support_screenshots` avec les
    coordonnées et le contexte."""
    if not is_signalmar_admin(user):
        raise HTTPException(403, "Fonction réservée au compte SignalMar admin.")

    from routers.diagnostics import (  # import local : évite un cycle au chargement
        SUPPORT_TMP, _session_get, _upload_sessions,
    )

    sess = await _session_get(body.upload_id)
    if not sess:
        raise HTTPException(404, "Session d'upload inconnue (relancez l'envoi).")
    missing = [i for i in range(sess["total_chunks"]) if i not in sess["received"]]
    if missing:
        raise HTTPException(422, f"Morceaux manquants : {missing[:10]}")

    buf = bytearray()
    for i in range(sess["total_chunks"]):
        part = SUPPORT_TMP / f"{body.upload_id}.{i}"
        if not part.exists():
            raise HTTPException(422, f"Morceau {i} introuvable sur le serveur.")
        buf += part.read_bytes()
        if len(buf) > _MAX_IMAGE_BYTES:
            raise HTTPException(413, "Capture trop volumineuse (max 4 Mo).")
    for i in range(sess["total_chunks"]):
        try:
            (SUPPORT_TMP / f"{body.upload_id}.{i}").unlink()
        except OSError:
            pass
    _upload_sessions.pop(body.upload_id, None)
    await srv.db.support_upload_sessions.delete_one({"id": body.upload_id})

    import base64
    mime = (body.mime or sess.get("mime") or "image/jpeg")
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    sid = _new_screenshot_id()
    doc = {
        "id": sid,
        "user_id": user.get("user_id"),
        "user_phone": user.get("phone"),
        "created_at": datetime.now(timezone.utc),
        "image_b64": f"data:{mime};base64," + base64.b64encode(bytes(buf)).decode("ascii"),
        "lat": body.lat,
        "lng": body.lng,
        "depth_zh_m": body.depth_zh_m,
        "comment": body.comment,
        "route_id": body.route_id,
        "context": body.context or {},
        "transport": "chunked",
        "has_image": True,
        "size_bytes": len(buf),
    }
    await srv.db.support_screenshots.insert_one(doc)
    logger.info(
        "support screenshot (chunked) uploaded id=%s user=%s route=%s coords=(%s,%s) size=%d",
        sid, user.get("user_id"), body.route_id, body.lat, body.lng, len(buf),
    )
    return {"ok": True, "id": sid, "size": len(buf),
            "created_at": doc["created_at"].isoformat()}


@router.get("/inbox")
async def support_inbox(user: dict = Depends(current_user)):
    """03/08/2026 (demande armateur) — « VÉRIFIER LA RÉCEPTION ».

    L'armateur a envoyé des captures qui ne sont jamais arrivées sans qu'il
    puisse le savoir. Cet endpoint lui dit, depuis l'app, ce que le serveur a
    RÉELLEMENT reçu : captures (avec ou sans image), fichiers assemblés
    (enregistrements d'écran) et bundles de logs, les plus récents d'abord."""
    if not is_signalmar_admin(user):
        raise HTTPException(403, "Fonction réservée au compte SignalMar admin.")

    from routers.diagnostics import SUPPORT_DIR

    shots = []
    async for d in srv.db.support_screenshots.find(
        {}, {"_id": 0, "image_b64": 0}
    ).sort("created_at", -1).limit(15):
        shots.append({
            "id": d.get("id"),
            "created_at": (d.get("created_at").isoformat()
                           if d.get("created_at") else None),
            "lat": d.get("lat"), "lng": d.get("lng"),
            "has_image": bool(d.get("has_image", True)),
            "size_bytes": d.get("size_bytes"),
            "transport": d.get("transport") or "single",
            "route_id": d.get("route_id"),
        })

    files = []
    try:
        entries = sorted(
            (f for f in SUPPORT_DIR.iterdir() if f.is_file()),
            key=lambda f: f.stat().st_mtime, reverse=True,
        )[:10]
        files = [
            {"filename": f.name, "size_bytes": f.stat().st_size,
             "modified_at": datetime.fromtimestamp(
                 f.stat().st_mtime, tz=timezone.utc).isoformat()}
            for f in entries
        ]
    except OSError:
        files = []

    logs = []
    async for d in srv.db.diagnostics.find(
        {}, {"_id": 0, "logs": 0, "logs_text": 0, "payload": 0}
    ).sort("created_at", -1).limit(10):
        logs.append({
            "created_at": (d.get("created_at").isoformat()
                           if d.get("created_at") else None),
            "user_agent": (str(d.get("user_agent") or ""))[:60],
        })

    return {"screenshots": shots, "files": files, "logs": logs,
             "server_time": datetime.now(timezone.utc).isoformat()}


@router.get("/screenshots")
async def list_screenshots(user: dict = Depends(current_user), limit: int = 50):
    """Liste les captures récentes (sans le champ image, allégé)."""
    if not is_signalmar_admin(user):
        raise HTTPException(403, "Fonction réservée au compte SignalMar admin.")
    limit = max(1, min(200, limit))
    docs = await srv.db.support_screenshots.find(
        {}, {"_id": 0, "image_b64": 0},
    ).sort("created_at", -1).to_list(limit)
    return {"screenshots": docs, "count": len(docs)}


@router.get("/screenshot/{sid}")
async def get_screenshot(sid: str, user: dict = Depends(current_user)):
    """Retourne le document complet (avec image_b64) pour inspection."""
    if not is_signalmar_admin(user):
        raise HTTPException(403, "Fonction réservée au compte SignalMar admin.")
    doc = await srv.db.support_screenshots.find_one({"id": sid.strip()}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Capture introuvable.")
    return doc


@router.get("/screenshot/{sid}/image")
async def get_screenshot_image(sid: str, user: dict = Depends(current_user)):
    """Retourne l'image décodée (image/jpeg ou image/png) — utile pour un
    aperçu direct dans le navigateur/outil de debug."""
    if not is_signalmar_admin(user):
        raise HTTPException(403, "Fonction réservée au compte SignalMar admin.")
    doc = await srv.db.support_screenshots.find_one({"id": sid.strip()}, {"_id": 0, "image_b64": 1})
    if not doc or not doc.get("image_b64"):
        raise HTTPException(404, "Image introuvable.")
    import base64
    raw = doc["image_b64"]
    mime = "image/jpeg"
    if raw.startswith("data:"):
        try:
            head, payload = raw.split(",", 1)
            mime = head.split(";")[0].removeprefix("data:") or mime
        except ValueError:
            payload = raw
    else:
        payload = raw
    try:
        data = base64.b64decode(payload, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Image corrompue : {exc}")
    return Response(content=data, media_type=mime)
