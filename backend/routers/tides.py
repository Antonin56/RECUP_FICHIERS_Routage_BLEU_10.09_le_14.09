"""SignalMar — API marées (20/07/2026). GET /api/tides/nearest?lat&lng →
port le plus proche + horaires/hauteurs BM-PM + coefficient approché.
Public (données de prédiction, aucune info utilisateur)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from core.tides import tide_curve, tides_for

logger = logging.getLogger("signalmar.tides")
router = APIRouter(prefix="/tides", tags=["tides"])


@router.get("/nearest")
async def get_nearest_tides(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    try:
        return await tides_for(lat, lng)
    except Exception as e:  # réseau Open-Meteo, parsing…
        logger.warning("tides fetch failed: %s", e)
        raise HTTPException(503, "Marées momentanément indisponibles — réessayez.")


@router.get("/curve")
async def get_tide_curve(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """28/07 (demande armateur) — mini-graphe de marée de la RouteCard :
    courbe 24 h (pas 30 min) au port le plus proche, hauteurs ≈/ZH."""
    import time as _time

    now = float(int(_time.time() // 600) * 600)
    curve = await tide_curve(lat, lng, now, hours=24.0, step_s=1800.0)
    if curve is None:
        raise HTTPException(503, "Marées momentanément indisponibles — réessayez.")
    return curve
