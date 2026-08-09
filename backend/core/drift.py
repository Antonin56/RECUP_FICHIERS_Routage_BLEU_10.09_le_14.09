"""Drift cone physics + Open-Meteo/Météo-France marine fetch (P0 decouple).

Contains all the drift-cone-related code previously living in ``server.py``.
No HTTP glue — just pure math + one async fetcher. Endpoints in
``routers/reports.py`` and ``routers/moderation.py`` reach these helpers
via the ``server`` re-exports so the ``import server as srv`` API stays
unchanged.

Public API (all re-exported by ``server.py``):
    - Geo helpers: haversine_km, offset_point
    - Config: DRIFT_LEEWAY, DRIFT_CONE_HALF_ANGLE_DEG, DRIFT_CONE_ARC_STEPS,
              DRIFT_CONE_HOURS, SUBTYPE_DRIFT
    - Predicates: subtype_drift_weights, is_animal_dead, drift_cone_eligible
    - Fetch:      fetch_marine_drift_inputs
    - Compute:    compute_drift_cone, refresh_drift_cone
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Optional

import httpx

from core.db import db

logger = logging.getLogger("signalmar.drift")


# ---------------------------------------------------------------------------
# Geo helpers (used across the codebase, not just for drift)
# ---------------------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def offset_point(lat: float, lng: float, bearing_deg: float,
                 distance_km: float) -> tuple[float, float]:
    """Destination point given start, initial bearing, and distance."""
    R = 6371.0
    br = math.radians(bearing_deg)
    d = distance_km / R
    lat1 = math.radians(lat)
    lng1 = math.radians(lng)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d)
        + math.cos(lat1) * math.sin(d) * math.cos(br)
    )
    lng2 = lng1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lng2)


# ---------------------------------------------------------------------------
# Drift-cone config
# ---------------------------------------------------------------------------
# Phase E.3 — leeway bumped from 3% → 5% to align with NATO SAR leeway tables
# for floating debris / OFNI. The per-subtype V weight still scales the
# effective leeway (object-type differentiation).
DRIFT_LEEWAY = 0.05
DRIFT_CONE_HALF_ANGLE_DEG = 18.0
DRIFT_CONE_ARC_STEPS = 14
DRIFT_CONE_HOURS = 1.0

# Mirror of `src/lib/report-types.ts` drift weights for the eligible subtypes.
SUBTYPE_DRIFT: dict[tuple[str, str], dict[str, int]] = {
    # Obstacles à la navigation
    ("obstacle_nav", "ofni"):           {"V": 6, "C": 4},
    ("obstacle_nav", "bouee_peche"):    {"V": 8, "C": 2},
    ("obstacle_nav", "conteneur"):      {"V": 1, "C": 9},
    ("obstacle_nav", "bois_flottant"):  {"V": 7, "C": 3},
    # 24/07/2026 (demande armateur) — nouveaux obstacles DÉRIVANTS.
    ("obstacle_nav", "embarcation_derive"): {"V": 6, "C": 4},
    ("obstacle_nav", "nappe_sargasses"):    {"V": 3, "C": 7},
    # Animaux marins — cone only for floating / drifting corpses.
    ("animal_marin", "mammifere"):      {"V": 4, "C": 6},
    ("animal_marin", "oiseau"):         {"V": 8, "C": 2},
    ("animal_marin", "autre_animal"):   {"V": 5, "C": 5},
    # Pollutions
    ("pollution", "pollution_cote"):       {"V": 4, "C": 6},
    ("pollution", "pollution_locale"):     {"V": 5, "C": 5},
    ("pollution", "pollution_importante"): {"V": 4, "C": 6},
}


def subtype_drift_weights(rtype: Optional[str],
                          subtype: Optional[str]) -> Optional[dict]:
    if not rtype or not subtype:
        return None
    return SUBTYPE_DRIFT.get((rtype, subtype))


def is_animal_dead(extras: Optional[dict]) -> bool:
    if not extras:
        return False
    h = (extras.get("health") or "").lower()
    return h.startswith("dead")


def drift_cone_eligible(rtype: Optional[str], subtype: Optional[str],
                        extras: Optional[dict]) -> bool:
    if not subtype_drift_weights(rtype, subtype):
        return False
    if rtype == "animal_marin":
        return is_animal_dead(extras)
    return True


# ---------------------------------------------------------------------------
# Marine data fetch (wind + current at a point)
# ---------------------------------------------------------------------------
async def fetch_marine_drift_inputs(lat: float,
                                    lng: float) -> Optional[dict]:
    """Fetch wind + sea-current vector at (lat, lng).

    Wind: Météo-France AROME/ARPEGE preferred, Open-Meteo fallback.
    Currents: always Open-Meteo Marine (MF has no ocean currents).
    """
    from core.meteofrance import get_wind_at  # lazy: keep startup fast

    wind_source = "Open-Meteo"
    wind_speed_ms: Optional[float] = None
    wind_to_deg: Optional[float] = None

    # 1) Try Météo-France (high-resolution). Silent fallback on any issue.
    try:
        mf = await get_wind_at(lat, lng, db=db)
        if mf and mf.get("speed_ms") is not None and mf.get("to_deg") is not None:
            wind_speed_ms = float(mf["speed_ms"])
            wind_to_deg = float(mf["to_deg"])
            wind_source = str(mf.get("source") or "Météo-France")
    except Exception as e:
        logger.warning("MF wind fetch failed, falling back to Open-Meteo: %s", e)

    try:
        async with httpx.AsyncClient(timeout=6.0) as cli:
            mr = await cli.get(
                "https://marine-api.open-meteo.com/v1/marine",
                params={
                    "latitude": round(lat, 4), "longitude": round(lng, 4),
                    "hourly": "ocean_current_velocity,ocean_current_direction",
                    "forecast_days": 1,
                },
            )
            wr = None
            if wind_speed_ms is None or wind_to_deg is None:
                wr = await cli.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": round(lat, 4), "longitude": round(lng, 4),
                        "hourly": "wind_speed_10m,wind_direction_10m",
                        "windspeed_unit": "ms",
                        "forecast_days": 1,
                    },
                )
        if mr.status_code != 200:
            return None
        mh = (mr.json().get("hourly") or {})
        _now_hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")

        def _pick_current_hour(hourly: dict, key: str) -> Optional[float]:
            times = hourly.get("time") or []
            vals = hourly.get(key) or []
            for i, t in enumerate(times):
                if isinstance(t, str) and t.startswith(_now_hour_key):
                    if i < len(vals) and vals[i] is not None:
                        return float(vals[i])
                    break
            for v in vals:
                if v is not None:
                    return float(v)
            return None

        c_v = _pick_current_hour(mh, "ocean_current_velocity")
        c_d = _pick_current_hour(mh, "ocean_current_direction")
        if wr is not None and wr.status_code == 200:
            wh = (wr.json().get("hourly") or {})
            w_v = _pick_current_hour(wh, "wind_speed_10m")
            w_d = _pick_current_hour(wh, "wind_direction_10m")
            if w_v is not None and w_d is not None:
                wind_speed_ms = float(w_v)
                # Open-Meteo → "from" bearing; convert to "to".
                wind_to_deg = (float(w_d) + 180.0) % 360.0
                wind_source = "Open-Meteo"
        if wind_speed_ms is None or wind_to_deg is None:
            return None
        if c_v is None or c_d is None:
            return None
        current_source = "Open-Meteo Marine (~8 km, global)"
        return {
            "wind_speed_ms": wind_speed_ms,
            "wind_to_deg": wind_to_deg,
            "wind_source": wind_source,
            "wind_confidence": "high" if wind_source.startswith("AROME") else "medium",
            "current_speed_ms": float(c_v),
            "current_to_deg": float(c_d),
            "current_source": current_source,
            "current_confidence": "low",
        }
    except Exception as e:
        logger.warning("marine drift inputs failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Cone compute
# ---------------------------------------------------------------------------
def compute_drift_cone(lat: float, lng: float, V: int, C: int,
                       marine: dict, hours: float,
                       override_bearing_deg: Optional[float] = None) -> dict:
    """Project a drift cone forward by `hours` from the report point."""
    def to_xy(speed: float, bearing_to_deg: float) -> tuple[float, float]:
        b = math.radians(bearing_to_deg)
        return speed * math.sin(b), speed * math.cos(b)

    wx, wy = to_xy(
        marine["wind_speed_ms"] * (V / 10.0) * DRIFT_LEEWAY,
        marine["wind_to_deg"],
    )
    cx, cy = to_xy(
        marine["current_speed_ms"] * (C / 10.0),
        marine["current_to_deg"],
    )
    rx, ry = wx + cx, wy + cy
    mag_ms = math.hypot(rx, ry)
    if mag_ms <= 1e-6:
        algo_bearing = 0.0
    else:
        algo_bearing = (math.degrees(math.atan2(rx, ry)) + 360.0) % 360.0

    if override_bearing_deg is not None:
        bearing = float(override_bearing_deg) % 360.0
        bearing_source = "user"
    else:
        bearing = algo_bearing
        bearing_source = "auto"

    if mag_ms <= 1e-6:
        return {
            "bearing_deg": round(bearing, 1),
            "algo_bearing_deg": round(algo_bearing, 1),
            "bearing_source": bearing_source,
            "distance_km": 0.0,
            "polygon": [{"lat": lat, "lng": lng}] * 3,
            "wind_to_deg": round(marine["wind_to_deg"], 1),
            "wind_speed_ms": round(marine["wind_speed_ms"], 2),
            "current_to_deg": round(marine["current_to_deg"], 1),
            "current_speed_ms": round(marine["current_speed_ms"], 2),
        }
    distance_km = (mag_ms * hours * 3600.0) / 1000.0
    polygon: list[tuple[float, float]] = [(lat, lng)]
    if DRIFT_CONE_ARC_STEPS >= 2:
        start = bearing - DRIFT_CONE_HALF_ANGLE_DEG
        for i in range(DRIFT_CONE_ARC_STEPS):
            t = i / (DRIFT_CONE_ARC_STEPS - 1)
            br = start + 2 * DRIFT_CONE_HALF_ANGLE_DEG * t
            p = offset_point(lat, lng, br, distance_km)
            polygon.append(p)
    polygon.append((lat, lng))
    return {
        "bearing_deg": round(bearing, 1),
        "algo_bearing_deg": round(algo_bearing, 1),
        "bearing_source": bearing_source,
        "distance_km": round(distance_km, 3),
        "polygon": [{"lat": round(p[0], 6), "lng": round(p[1], 6)} for p in polygon],
        "wind_to_deg": round(marine["wind_to_deg"], 1),
        "wind_speed_ms": round(marine["wind_speed_ms"], 2),
        "wind_source": marine.get("wind_source", "Open-Meteo"),
        "wind_confidence": marine.get("wind_confidence", "medium"),
        "current_to_deg": round(marine["current_to_deg"], 1),
        "current_speed_ms": round(marine["current_speed_ms"], 2),
        "current_source": marine.get("current_source", "Open-Meteo Marine"),
        "current_confidence": marine.get("current_confidence", "low"),
    }


# ---------------------------------------------------------------------------
# Distance côte (13/07/2026) — bande côtière des 20 km
# ---------------------------------------------------------------------------
# Le modèle de courants (SMOC, maille 0,08° ≈ 8 km) n'est PAS fiable à moins
# de ~20 km de TOUTE terre — îles comprises (Belle-Île, Groix, Ouessant :
# raz et goulets non résolus, ex. Fromveur ~8 nds invisibles au modèle).
# Détection : 96 points échantillonnés (24 caps × rayons 5/10/15/20 km) via
# l'API Elevation Open-Meteo (DEM Copernicus 90 m, gratuit, 1 seul appel
# batch). Terre = élévation > 0,5 m. Cache Mongo + mémoire (cellules ~2 km).
# Fail-safe : au moindre doute (API HS) → considéré CÔTIER (vent seul).
COASTAL_BAND_KM = 20.0
_coast_cache: dict[tuple[int, int], bool] = {}


async def has_land_within_km(lat: float, lng: float,
                             radius_km: float = COASTAL_BAND_KM) -> bool:
    """True si une terre (continent OU île) est à moins de radius_km."""
    key = (int(round(lat * 50)), int(round(lng * 50)))  # cellules ~2 km
    if key in _coast_cache:
        return _coast_cache[key]
    try:
        cached = await db.coast_cache.find_one({"k": list(key)}, {"_id": 0, "v": 1})
        if cached is not None:
            _coast_cache[key] = bool(cached["v"])
            return _coast_cache[key]
    except Exception:
        pass

    pts: list[tuple[float, float]] = []
    # 6 anneaux × 30 caps (12°) = 180 points — espacement ≤ 4,2 km au pire
    # (anneau 20 km) : les îles ≥ 3 km (Ouessant, Groix, Sein…) sont vues.
    for r_km in (3.0, 6.0, 9.0, 12.0, 16.0, radius_km):
        for i in range(30):
            pts.append(offset_point(lat, lng, i * 12.0, r_km))
    try:
        found_land = False
        async with httpx.AsyncClient(timeout=8.0) as cli:
            # L'API Elevation accepte ~100 coordonnées max → lots de 90.
            for i0 in range(0, len(pts), 90):
                chunk = pts[i0:i0 + 90]
                params = {
                    "latitude": ",".join(f"{p[0]:.4f}" for p in chunk),
                    "longitude": ",".join(f"{p[1]:.4f}" for p in chunk),
                }
                resp = await cli.get("https://api.open-meteo.com/v1/elevation", params=params)
                if resp.status_code != 200:
                    # Rate-limit / indispo : 2 retries avec backoff avant le
                    # fail-safe (les seeds en rafale déclenchaient de faux
                    # « côtier » au large — constaté le 13/07).
                    for wait_s in (1.5, 4.0):
                        await asyncio.sleep(wait_s)
                        resp = await cli.get("https://api.open-meteo.com/v1/elevation", params=params)
                        if resp.status_code == 200:
                            break
                if resp.status_code != 200:
                    # Fail-safe SANS mise en cache : verdict provisoire côtier,
                    # re-tenté au prochain calcul (évite d'empoisonner le cache
                    # avec un faux « côtier » sur un simple rate-limit).
                    logger.warning("elevation API status %s — fail-safe coastal (non caché)", resp.status_code)
                    return True
                elev = resp.json().get("elevation") or []
                if any(e is not None and float(e) > 0.5 for e in elev):
                    found_land = True
                    break
        verdict = found_land
    except Exception as e:
        logger.warning("elevation API failed (%s) — fail-safe coastal (non caché)", e)
        return True
    _coast_cache[key] = verdict
    try:
        await db.coast_cache.update_one(
            {"k": list(key)}, {"$set": {"v": verdict}}, upsert=True,
        )
    except Exception:
        pass
    return verdict


async def refresh_drift_cone(rid: str, lat: float, lng: float,
                             rtype: Optional[str], subtype: Optional[str],
                             extras: Optional[dict],
                             heading: Optional[float] = None) -> Optional[dict]:
    """Compute (or clear) the drift cone for the given report."""
    if not drift_cone_eligible(rtype, subtype, extras):
        try:
            await db.reports.update_one({"id": rid}, {"$unset": {"drift_cone": ""}})
        except Exception:
            pass
        return None
    weights = subtype_drift_weights(rtype, subtype)
    if not weights:
        return None
    marine = await fetch_marine_drift_inputs(lat, lng)
    if not marine:
        return None
    # Bande côtière des 20 km (13/07/2026) : le courant modèle n'y est pas
    # fiable → cône calculé au VENT SEUL, flag wind_only pour l'infobulle.
    wind_only = await has_land_within_km(lat, lng, COASTAL_BAND_KM)
    if wind_only:
        marine = {
            **marine,
            "current_speed_ms": 0.0,
            "current_source": "ignoré (< 20 km des côtes)",
            "current_confidence": "none",
        }
    cone = compute_drift_cone(
        lat, lng, weights["V"], weights["C"],
        marine, DRIFT_CONE_HOURS,
        override_bearing_deg=heading,
    )
    payload = {
        **cone,
        "wind_only": wind_only,
        "hours": DRIFT_CONE_HOURS,
        "weights": weights,
        "computed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    try:
        await db.reports.update_one({"id": rid}, {"$set": {"drift_cone": payload}})
    except Exception as e:
        logger.warning("drift_cone persist failed: %s", e)
    return payload


__all__ = [
    "haversine_km", "offset_point",
    "DRIFT_LEEWAY", "DRIFT_CONE_HALF_ANGLE_DEG", "DRIFT_CONE_ARC_STEPS",
    "DRIFT_CONE_HOURS", "SUBTYPE_DRIFT",
    "subtype_drift_weights", "is_animal_dead", "drift_cone_eligible",
    "fetch_marine_drift_inputs", "compute_drift_cone", "refresh_drift_cone",
    "has_land_within_km", "COASTAL_BAND_KM",
]
