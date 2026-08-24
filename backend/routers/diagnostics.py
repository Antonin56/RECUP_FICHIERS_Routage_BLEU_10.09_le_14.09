"""Diagnostic + support upload endpoints.

Endpoints (mounted under /api):
- GET  /api/diagnostics/ping → lightweight reachability check
- POST /api/diagnostics      → ingest a bundle (logs + snapshot)
- GET  /api/diagnostics/meteofrance → verifies MF OAuth2 + AROME/ARPEGE fetch
- GET  /api/downloads/signalmar-v2-presentation.pdf → V2 presentation PDF
- GET  /api/                 → ping (kept as ``root`` for legacy clients)
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

import server as srv

router = APIRouter(tags=["diagnostics"])

# ─────────────────────────────────────────────────────────────────────────────
# Upload support (13/07/2026) — vidéos / captures d'écran envoyées au support
# depuis Profil → « Envoyer un enregistrement d'écran au support ».
# Upload CHUNKÉ (512 Ko base64) pour passer sous les limites du proxy ingress.
# Fichiers assemblés dans /app/backend/uploads/support/ + méta dans Mongo
# (collection support_uploads) — consultables par l'agent pour le debugging.
# ─────────────────────────────────────────────────────────────────────────────
SUPPORT_DIR = Path(__file__).resolve().parent.parent / "uploads" / "support"
SUPPORT_TMP = SUPPORT_DIR / "tmp"
SUPPORT_RETENTION_HOURS = 12  # demande user 13/07 : rien conservé au-delà de 12 h
# 03/08/2026 — taille de chunk RECOMMANDÉE à l'app. Les envois en un seul POST
# (~400 Ko à 100 Mo) étaient throttlés par l'ingress : l'armateur voyait
# « support screenshot failed {"status":429} » et la capture n'arrivait jamais.
# 96 Ko binaires ≈ 128 Ko en base64 par requête : sous le seuil de throttling.
SUPPORT_CHUNK_HINT = 96 * 1024
_upload_sessions: Dict[str, Dict[str, Any]] = {}


async def purge_expired_support_uploads() -> int:
    """Supprime les uploads support de plus de SUPPORT_RETENTION_HOURS :
    documents Mongo + fichiers assemblés + chunks temporaires orphelins +
    sessions mémoire périmées. Appelé par la boucle d'archivage (server.py,
    toutes les 10 min). Retourne le nombre de documents purgés."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=SUPPORT_RETENTION_HOURS)
    purged = 0
    async for doc in srv.db.support_uploads.find(
        {"created_at": {"$lt": cutoff}}, {"_id": 1, "path": 1}
    ):
        try:
            Path(doc.get("path") or "").unlink(missing_ok=True)
        except OSError:
            pass
        await srv.db.support_uploads.delete_one({"_id": doc["_id"]})
        purged += 1
    # Fichiers orphelins (assemblés ou chunks tmp) plus vieux que la rétention.
    now = time.time()
    for d in (SUPPORT_TMP, SUPPORT_DIR):
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file() and now - f.stat().st_mtime > SUPPORT_RETENTION_HOURS * 3600:
                try:
                    f.unlink()
                except OSError:
                    pass
    # Sessions d'upload jamais complétées (6 h max).
    for uid, sess in list(_upload_sessions.items()):
        if now - sess.get("started_at", now) > 6 * 3600:
            _upload_sessions.pop(uid, None)
    return purged


class SupportUploadInit(BaseModel):
    filename: str
    mime: str = "application/octet-stream"
    total_chunks: int


class SupportUploadChunk(BaseModel):
    upload_id: str
    index: int
    data_b64: str


class SupportUploadComplete(BaseModel):
    upload_id: str
    note: Optional[str] = None


async def _session_get(upload_id: str) -> Optional[dict]:
    """Session d'upload, RÉSISTANTE au redémarrage du backend.

    03/08/2026 — les sessions n'étaient qu'en MÉMOIRE : un redémarrage (ou un
    déploiement) pendant un envoi renvoyait « Session d'upload inconnue » et
    l'armateur perdait sa capture. Elles sont désormais persistées en base et
    la liste des chunks déjà reçus est reconstituée depuis le DISQUE."""
    sess = _upload_sessions.get(upload_id)
    if sess is not None:
        return sess
    doc = await srv.db.support_upload_sessions.find_one({"id": upload_id}, {"_id": 0})
    if not doc:
        return None
    received: set[int] = set()
    for f in SUPPORT_TMP.glob(f"{upload_id}.*"):
        try:
            received.add(int(f.name.rsplit(".", 1)[1]))
        except (IndexError, ValueError):
            pass
    sess = {
        "user_id": doc.get("user_id"),
        "filename": doc.get("filename") or "capture",
        "mime": doc.get("mime") or "application/octet-stream",
        "total_chunks": int(doc.get("total_chunks") or 1),
        "received": received,
        "started_at": time.time(),
    }
    _upload_sessions[upload_id] = sess
    return sess


@router.post("/support/upload/init")
async def support_upload_init(body: SupportUploadInit, request: Request):
    u = await srv.current_user(request)
    if not u:
        raise HTTPException(status_code=401, detail="Auth required")
    if body.total_chunks < 1 or body.total_chunks > 2000:  # ~190 Mo en 96 Ko
        raise HTTPException(status_code=422, detail="total_chunks invalide")
    upload_id = uuid.uuid4().hex
    SUPPORT_TMP.mkdir(parents=True, exist_ok=True)
    sess = {
        "user_id": u["user_id"],
        "filename": os.path.basename(body.filename)[:120] or "capture",
        "mime": body.mime[:80],
        "total_chunks": body.total_chunks,
        "received": set(),
        "started_at": time.time(),
    }
    _upload_sessions[upload_id] = sess
    # Persistée : un redémarrage du backend pendant l'envoi ne doit plus
    # perdre la capture (cf. _session_get).
    await srv.db.support_upload_sessions.insert_one({
        "id": upload_id,
        "user_id": sess["user_id"],
        "filename": sess["filename"],
        "mime": sess["mime"],
        "total_chunks": sess["total_chunks"],
        "created_at": datetime.now(timezone.utc),
    })
    return {"upload_id": upload_id, "chunk_size": SUPPORT_CHUNK_HINT}


@router.post("/support/upload/chunk")
async def support_upload_chunk(body: SupportUploadChunk):
    import base64
    sess = await _session_get(body.upload_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session d'upload inconnue (relancez l'envoi).")
    if not (0 <= body.index < sess["total_chunks"]):
        raise HTTPException(status_code=422, detail="index de chunk invalide")
    try:
        raw = base64.b64decode(body.data_b64)
    except Exception:
        raise HTTPException(status_code=422, detail="chunk base64 invalide")
    (SUPPORT_TMP / f"{body.upload_id}.{body.index}").write_bytes(raw)
    sess["received"].add(body.index)
    return {"ok": True, "received": len(sess["received"]), "total": sess["total_chunks"]}


@router.post("/support/upload/complete")
async def support_upload_complete(body: SupportUploadComplete):
    sess = await _session_get(body.upload_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session d'upload inconnue.")
    missing = [i for i in range(sess["total_chunks"]) if i not in sess["received"]]
    if missing:
        raise HTTPException(status_code=422, detail=f"chunks manquants: {missing[:10]}")
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    dest = SUPPORT_DIR / f"{body.upload_id}_{sess['filename']}"
    with dest.open("wb") as out:
        for i in range(sess["total_chunks"]):
            part = SUPPORT_TMP / f"{body.upload_id}.{i}"
            out.write(part.read_bytes())
            try:
                part.unlink()
            except OSError:
                pass
    size = dest.stat().st_size
    await srv.db.support_uploads.insert_one({
        "id": body.upload_id,
        "user_id": sess["user_id"],
        "filename": sess["filename"],
        "mime": sess["mime"],
        "size": size,
        "path": str(dest),
        "note": (body.note or "")[:500],
        "created_at": datetime.now(timezone.utc),
    })
    _upload_sessions.pop(body.upload_id, None)
    await srv.db.support_upload_sessions.delete_one({"id": body.upload_id})
    return {"ok": True, "size": size, "filename": sess["filename"]}


@router.get("/downloads/signalmar-v2-presentation.pdf")
async def download_v2_presentation():
    """Serve the SignalMar V2 presentation brochure as an inline PDF."""
    p = Path("/app/SignalMar_V2_Presentation.pdf")
    if not p.exists():
        raise HTTPException(404, "presentation file not found")
    return FileResponse(
        path=str(p),
        media_type="application/pdf",
        filename="SignalMar_V2_Presentation.pdf",
    )


class DiagnosticIn(BaseModel):
    snapshot: Optional[Dict[str, Any]] = None
    logs_text: Optional[str] = None
    user_email: Optional[str] = None
    user_id: Optional[str] = None
    note: Optional[str] = None


@router.get("/")
async def root():
    return {"name": "SignMar API", "ok": True}


@router.get("/diagnostics/ping")
async def diagnostics_ping():
    """Lightweight ping used by the in-app Diagnostic screen to measure
    backend reachability + latency. No auth required."""
    return {"ok": True, "ts": datetime.utcnow().isoformat()}


@router.post("/diagnostics", status_code=201)
async def diagnostics_post(payload: DiagnosticIn, request: Request):
    """Stocke un bundle de diagnostic envoyé par l'app (logs + snapshot)
    pour qu'un membre du support puisse le consulter plus tard."""
    # 14/08 (audit QA FND-031) — attribution : si le client est connecté
    # (header Authorization présent), le diagnostic est rattaché au compte
    # même quand le payload n'a pas renseigné user_id/email.
    uid = payload.user_id
    uemail = payload.user_email
    if not uid:
        try:
            u = await srv.current_user(request)
            uid = u.get("user_id")
            uemail = uemail or u.get("email")
        except Exception:  # noqa: BLE001 — endpoint volontairement sans auth
            pass
    doc = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.utcnow(),
        "snapshot": payload.snapshot,
        "logs_text": (payload.logs_text or "")[:200_000],  # cap 200 KB
        "user_email": uemail,
        "user_id": uid,
        "note": payload.note,
        "client_ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
    await srv.db.diagnostics.insert_one(doc)
    srv.logger.info(
        "diagnostic received id=%s user=%s logs=%d bytes",
        doc["id"], payload.user_email, len(doc["logs_text"] or ""),
    )
    return {"ok": True, "id": doc["id"]}


@router.get("/diagnostics/meteofrance")
async def diagnostics_meteofrance(
    lat: float = Query(47.65, description="Latitude (default: Golfe du Morbihan)"),
    lng: float = Query(-2.75, description="Longitude"),
    clear_cache: bool = Query(False, description="If true, wipe cached tile before fetching"),
):
    """Runs a live probe against Météo-France (OAuth2 → AROME/ARPEGE WCS → GRIB2).

    Returns a structured report suitable for the frontend Diagnostic screen and
    for the backend testing_agent. Never raises: every failure surfaces as a
    field in the JSON response so callers can pinpoint what went wrong.
    """
    from core import meteofrance as mf  # local import to avoid startup cost

    out: Dict[str, Any] = {
        "input": {"lat": lat, "lng": lng, "clear_cache": clear_cache},
        "env_configured": bool(os.environ.get("METEOFRANCE_APPLICATION_ID", "").strip()),
        "eccodes": None,
        "token": {"ok": False, "cached": False, "expires_at": None},
        "model_picked": "AROME" if mf._in_arome(lat, lng) else "ARPEGE",
        "wind": None,
        "latency_ms": None,
        "cache": {"before": None, "after": None},
        "errors": [],
    }

    # 1) Confirm eccodes is importable (else GRIB decoding silently returns None).
    try:
        import eccodes  # noqa: F401
        out["eccodes"] = getattr(eccodes, "__version__", "ok")
    except Exception as e:
        out["errors"].append(f"eccodes import failed: {e!r}")

    # 2) Token snapshot (before request).
    tok_before = mf._token_cache.get("access_token")
    exp_before = float(mf._token_cache.get("expires_at") or 0)
    out["token"]["cached"] = bool(tok_before)
    out["token"]["expires_at"] = (
        datetime.utcfromtimestamp(exp_before).isoformat() + "Z" if exp_before else None
    )

    # 3) Optional cache reset for the probed tile.
    tile = mf._tile_id(lat, lng)
    hour_key = mf._hour_key(datetime.utcnow())
    # Track both AROME and ARPEGE cache slots (AROME may fall back to ARPEGE).
    cache_ids = [f"AROME:{tile}:{hour_key}", f"ARPEGE:{tile}:{hour_key}"]
    try:
        docs = await srv.db.wind_cache.find(
            {"_id": {"$in": cache_ids}}, {"_id": 1, "fetched_at": 1, "source": 1}
        ).to_list(length=4)
        out["cache"]["before"] = [
            {"id": d["_id"], "fetched_at": d["fetched_at"].isoformat(),
             "source": d.get("source")}
            for d in docs
        ]
        if clear_cache:
            await srv.db.wind_cache.delete_many({"_id": {"$in": cache_ids}})
    except Exception as e:
        out["errors"].append(f"cache probe failed: {e!r}")

    # 4) Live fetch (timed).
    t0 = time.perf_counter()
    try:
        wind = await mf.get_wind_at(lat, lng, db=srv.db)
        out["wind"] = wind
    except Exception as e:
        out["errors"].append(f"get_wind_at raised: {e!r}")
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    # 5) Token snapshot (after request).
    tok_after = mf._token_cache.get("access_token")
    exp_after = float(mf._token_cache.get("expires_at") or 0)
    out["token"]["ok"] = bool(tok_after)
    out["token"]["refreshed_during_call"] = bool(tok_after) and tok_after != tok_before
    if exp_after:
        out["token"]["expires_at"] = datetime.utcfromtimestamp(exp_after).isoformat() + "Z"

    # 6) Cache snapshot (after).
    try:
        docs = await srv.db.wind_cache.find(
            {"_id": {"$in": cache_ids}}, {"_id": 1, "fetched_at": 1, "source": 1}
        ).to_list(length=4)
        out["cache"]["after"] = [
            {"id": d["_id"], "fetched_at": d["fetched_at"].isoformat(),
             "source": d.get("source")}
            for d in docs
        ]
    except Exception as e:
        out["errors"].append(f"cache post-probe failed: {e!r}")

    out["ok"] = bool(out["wind"]) and not out["errors"]
    return out


@router.get("/diagnostics/meteofrance/cache")
async def diagnostics_meteofrance_cache_stats():
    """Return quick stats on the wind_cache collection (size, oldest, newest)."""
    try:
        total = await srv.db.wind_cache.count_documents({})
        newest = await srv.db.wind_cache.find_one(sort=[("fetched_at", -1)])
        oldest = await srv.db.wind_cache.find_one(sort=[("fetched_at", 1)])
        by_source: Dict[str, int] = {}
        async for doc in srv.db.wind_cache.aggregate([
            {"$group": {"_id": "$source", "n": {"$sum": 1}}}
        ]):
            by_source[str(doc.get("_id") or "unknown")] = int(doc.get("n") or 0)
        return {
            "ok": True,
            "total": total,
            "by_source": by_source,
            "newest": newest.get("fetched_at").isoformat() if newest else None,
            "oldest": oldest.get("fetched_at").isoformat() if oldest else None,
        }
    except Exception as e:
        raise HTTPException(500, f"cache stats failed: {e!r}")
