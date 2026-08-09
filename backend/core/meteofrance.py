"""Phase E.6 — Météo-France AROME / ARPEGE integration.

This module provides high-precision wind data for the drift cone
computation, replacing (with graceful fallback) the previous Open-Meteo
call. It handles:

  1. OAuth2 auto-refresh (client_credentials against portail-api.meteofrance.fr)
  2. Model selection: AROME 1.3 km (≤ 50 NM from coast) or ARPEGE 0.1° Europe
  3. GRIB2 decoding via ``eccodes`` → (u_ms, v_ms, speed_ms, dir_deg)
  4. Per-tile MongoDB cache (TTL 30 min) — indexed on (model, tile_id, hour)
  5. Silent fallback (returns ``None``) so callers can use Open-Meteo instead

Design goals:
  - Never blocks the API response (all failures return ``None`` gracefully).
  - Never leaks the APPLICATION_ID beyond this module + os.environ.
  - Rate-friendly: default TTL 30 min per 5×5 km tile → ≤ 2 requests/tile/hour.

Environment:
  METEOFRANCE_APPLICATION_ID = base64("client_id:client_secret")  (in .env)

Usage:
  wind = await get_wind_at(lat=47.65, lng=-2.75, when_utc=datetime.utcnow())
  # → {'speed_ms': 3.65, 'to_deg': 92.1, 'source': 'AROME 1.3km',
  #    'u_ms': 3.6, 'v_ms': 0.5, 'age_s': 12}
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger("signmar.meteofrance")

# ── Constants ───────────────────────────────────────────────────────────────
TOKEN_URL = "https://portail-api.meteofrance.fr/token"
BASE_URL = "https://public-api.meteofrance.fr/public"
# AROME 1.3 km high-resolution, France + coastal waters up to ~50 NM offshore
AROME_WCS = f"{BASE_URL}/arome/1.0/wcs/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS"
# ARPEGE 0.1° Europe — fallback for offshore/DOM zones
ARPEGE_EU_WCS = f"{BASE_URL}/arpege/1.0/wcs/MF-NWP-GLOBAL-ARPEGE-01-EUROPE-WCS"

# AROME useful envelope (approximate; MF documents ~ -8°W→12°E, 38°N→53°N).
AROME_BBOX = {"lat_min": 38.0, "lat_max": 53.0, "lng_min": -8.0, "lng_max": 12.0}

# Cache tuning
TILE_KM = 5.0            # 5×5 km granularity
CACHE_TTL_MIN = 30       # tile is fresh for 30 minutes
TOKEN_REFRESH_SEC = 3300  # refresh at ~55 min (before the 60 min expiry)

# ── Module state (in-process, per uvicorn worker) ───────────────────────────
_token_cache: dict[str, object] = {"access_token": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()


# ── Token lifecycle ─────────────────────────────────────────────────────────
async def _get_valid_token() -> Optional[str]:
    """Return a valid OAuth2 access token; refresh via client_credentials if needed."""
    app_id = os.environ.get("METEOFRANCE_APPLICATION_ID", "").strip()
    if not app_id:
        logger.warning("METEOFRANCE_APPLICATION_ID not configured — MF disabled")
        return None

    now = datetime.now(timezone.utc).timestamp()
    tok = _token_cache.get("access_token")
    exp = float(_token_cache.get("expires_at") or 0)
    if tok and now < exp - 30:  # 30 s safety margin
        return str(tok)

    async with _token_lock:
        # Re-check under the lock in case another coroutine just refreshed.
        tok = _token_cache.get("access_token")
        exp = float(_token_cache.get("expires_at") or 0)
        if tok and now < exp - 30:
            return str(tok)
        try:
            async with httpx.AsyncClient(timeout=10, verify=True) as h:
                r = await h.post(
                    TOKEN_URL,
                    data={"grant_type": "client_credentials"},
                    headers={"Authorization": f"Basic {app_id}"},
                )
            if r.status_code != 200:
                logger.warning("MF token refresh HTTP %s: %s", r.status_code, r.text[:200])
                return None
            data = r.json()
            new_tok = data.get("access_token")
            expires_in = int(data.get("expires_in", 3600))
            if not new_tok:
                logger.warning("MF token response missing access_token")
                return None
            _token_cache["access_token"] = new_tok
            _token_cache["expires_at"] = now + min(expires_in, TOKEN_REFRESH_SEC)
            logger.info("MF token refreshed, expires in %ds", expires_in)
            return new_tok
        except Exception as e:
            logger.warning("MF token refresh failed: %s", e)
            return None


# ── Helpers ─────────────────────────────────────────────────────────────────
def _tile_id(lat: float, lng: float) -> str:
    """5×5 km tile identifier — 0.045° lat × 0.067° lng (approx at 45°N)."""
    lat_step = 0.045  # ≈ 5 km
    lng_step = 0.067  # ≈ 5 km at 45°N
    lat_bin = round(lat / lat_step)
    lng_bin = round(lng / lng_step)
    return f"{lat_bin}:{lng_bin}"


def _in_arome(lat: float, lng: float) -> bool:
    """Return True if the point is inside the AROME (France + coastal) envelope."""
    return (AROME_BBOX["lat_min"] <= lat <= AROME_BBOX["lat_max"]
            and AROME_BBOX["lng_min"] <= lng <= AROME_BBOX["lng_max"])


def _hour_key(when_utc: datetime) -> str:
    """Round to the nearest hour in ISO Z form for the WCS time subset."""
    d = when_utc.replace(minute=0, second=0, microsecond=0)
    return d.strftime("%Y-%m-%dT%H:00:00Z")


def _candidate_runs(model: str, when_utc: datetime) -> list[str]:
    """Return an ordered list of run timestamps to try (most recent first).

    - AROME runs every 3h (00/03/06/09/12/15/18/21), publishes ~4-6h later
    - ARPEGE runs every 6h (00/06/12/18), publishes ~3h later

    We start at now minus the publication lag and step back a few slots to
    survive brief publication delays.
    """
    if model == "AROME":
        stride = 3
        lag_h = 4
        n = 6  # ≈ last 18 h
    else:  # ARPEGE
        stride = 6
        lag_h = 3
        n = 4  # ≈ last 24 h
    base = when_utc - timedelta(hours=lag_h)
    # Snap to the previous slot boundary.
    hh = (base.hour // stride) * stride
    base = base.replace(hour=hh, minute=0, second=0, microsecond=0)
    return [(base - timedelta(hours=stride * i)).strftime("%Y-%m-%dT%H.00.00Z")
            for i in range(n)]


async def _wcs_get_coverage(
    wcs_url: str, coverage_id: str, lat: float, lng: float,
    when_utc: datetime, token: str,
) -> Optional[bytes]:
    """Fetch a small GRIB2 patch around (lat, lng) at the given hour."""
    # Tiny bbox around the point — enough for a single grid cell + neighbours.
    lat_min, lat_max = lat - 0.1, lat + 0.1
    lng_min, lng_max = lng - 0.1, lng + 0.1
    params = [
        ("service", "WCS"),
        ("version", "2.0.1"),
        ("coverageid", coverage_id),
        ("format", "application/wmo-grib"),
        ("subset", f"lat({lat_min},{lat_max})"),
        ("subset", f"long({lng_min},{lng_max})"),
        ("subset", "height(10)"),
        # Météo-France quirk: time value MUST NOT be quoted (contrary to
        # the WCS 2.0 spec which asks for `time("...")`).
        ("subset", f"time({_hour_key(when_utc)})"),
    ]
    try:
        async with httpx.AsyncClient(timeout=15, verify=True) as h:
            r = await h.get(
                f"{wcs_url}/GetCoverage",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code != 200:
            logger.warning("MF WCS %s HTTP %s: %s", coverage_id[:40], r.status_code, r.text[:200])
            return None
        if not r.content.startswith(b"GRIB"):
            logger.warning("MF WCS %s → non-GRIB response: %s", coverage_id[:40], r.content[:120])
            return None
        return r.content
    except Exception as e:
        logger.warning("MF WCS %s network error: %s", coverage_id[:40], e)
        return None


def _decode_grib_at(grib_bytes: bytes, lat: float, lng: float) -> Optional[float]:
    """Decode a GRIB2 blob and return the value nearest to (lat, lng), else None."""
    # eccodes needs a real file. Write to a temp file, decode, unlink.
    try:
        import eccodes  # local import so tests can run without the .so on hand
    except Exception:
        return None
    fd, path = tempfile.mkstemp(suffix=".grib2")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(grib_bytes)
        with open(path, "rb") as fh:
            h = eccodes.codes_grib_new_from_file(fh)
            if not h:
                return None
            try:
                # Find the value nearest to (lat, lng) — eccodes provides a helper.
                nearest = eccodes.codes_grib_find_nearest(h, lat, lng, is_lsm=0)
                if not nearest:
                    return None
                return float(nearest[0]["value"])
            finally:
                eccodes.codes_release(h)
    except Exception as e:
        logger.warning("GRIB decode failed: %s", e)
        return None
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


async def _cache_get(db, model: str, tile: str, hour_key: str):
    if db is None:
        return None
    doc = await db.wind_cache.find_one(
        {"_id": f"{model}:{tile}:{hour_key}"}, {"_id": 0}
    )
    if not doc:
        return None
    fetched = doc.get("fetched_at")
    if not fetched:
        return None
    # Motor/pymongo returns naive UTC datetimes by default — make aware.
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - fetched).total_seconds()
    if age > CACHE_TTL_MIN * 60:
        return None
    return doc


async def _cache_put(db, model: str, tile: str, hour_key: str, payload: dict):
    if db is None:
        return
    doc = {
        "_id": f"{model}:{tile}:{hour_key}",
        "model": model,
        "tile": tile,
        "hour_key": hour_key,
        "fetched_at": datetime.now(timezone.utc),
        **payload,
    }
    try:
        await db.wind_cache.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    except Exception as e:
        logger.warning("wind_cache put failed: %s", e)


# ── Public API ──────────────────────────────────────────────────────────────
async def get_wind_at(
    lat: float, lng: float,
    when_utc: Optional[datetime] = None,
    db=None,
) -> Optional[dict]:
    """High-precision 10 m wind at (lat, lng) via Météo-France models.

    Strategy:
      1. Cache lookup (30 min TTL per 5×5 km tile).
      2. AROME first (if in envelope), else ARPEGE.
      3. For each model, try the most recent runs until a GRIB2 is returned.
      4. Fetch U + V components at 10 m → derive speed & direction TO (drift).

    Returns None on any failure — callers should fall back to Open-Meteo.
    """
    if when_utc is None:
        when_utc = datetime.now(timezone.utc)
    hour_key = _hour_key(when_utc)
    tile = _tile_id(lat, lng)

    # 1) Cache
    for model in (["AROME", "ARPEGE"] if _in_arome(lat, lng) else ["ARPEGE"]):
        cached = await _cache_get(db, model, tile, hour_key)
        if cached and "speed_ms" in cached:
            return {
                "speed_ms": cached["speed_ms"],
                "to_deg": cached.get("to_deg"),
                "u_ms": cached.get("u_ms"),
                "v_ms": cached.get("v_ms"),
                "source": cached.get("source", model),
                "cached": True,
            }

    # 2) Token
    token = await _get_valid_token()
    if not token:
        return None

    # 3) Model + run selection, walking backwards on 404s.
    models_to_try = (
        [("AROME", AROME_WCS), ("ARPEGE", ARPEGE_EU_WCS)]
        if _in_arome(lat, lng)
        else [("ARPEGE", ARPEGE_EU_WCS)]
    )

    for model, wcs_url in models_to_try:
        for run in _candidate_runs(model, when_utc):
            u_cov = f"U_COMPONENT_OF_WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND___{run}"
            v_cov = f"V_COMPONENT_OF_WIND__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND___{run}"
            u_blob = await _wcs_get_coverage(wcs_url, u_cov, lat, lng, when_utc, token)
            if not u_blob:
                continue  # try previous run
            v_blob = await _wcs_get_coverage(wcs_url, v_cov, lat, lng, when_utc, token)
            if not v_blob:
                continue
            u_ms = _decode_grib_at(u_blob, lat, lng)
            v_ms = _decode_grib_at(v_blob, lat, lng)
            if u_ms is None or v_ms is None or math.isnan(u_ms) or math.isnan(v_ms):
                continue

            speed_ms = math.hypot(u_ms, v_ms)
            # Meteorological convention: (u, v) = eastward, northward components.
            # dir_from = atan2(-u, -v) in degrees; dir_to = (dir_from + 180) % 360.
            dir_from = (math.degrees(math.atan2(-u_ms, -v_ms)) + 360.0) % 360.0
            to_deg = (dir_from + 180.0) % 360.0

            source_label = f"{model} 1.3km" if model == "AROME" else f"{model} 0.1° Europe"
            payload = {
                "speed_ms": round(float(speed_ms), 3),
                "to_deg": round(float(to_deg), 1),
                "u_ms": round(float(u_ms), 3),
                "v_ms": round(float(v_ms), 3),
                "source": source_label,
                "run": run,
            }
            await _cache_put(db, model, tile, hour_key, payload)
            logger.info(
                "MF wind %s run=%s @(%.3f,%.3f) → %.2f m/s to=%.0f°",
                model, run, lat, lng, speed_ms, to_deg,
            )
            return {**payload, "cached": False}

    return None
