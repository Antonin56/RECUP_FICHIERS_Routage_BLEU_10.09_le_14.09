"""Marine weather proxy → Open-Meteo Marine + Forecast.

Endpoints (mounted under /api):
- GET /api/weather/marine?lat=&lng= → alerts + current conditions
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter

import server as srv

router = APIRouter(tags=["weather"])


@router.get("/weather/marine")
async def marine_weather(lat: float, lng: float):
    """Proxy Open-Meteo Marine + standard forecast → alerts."""
    try:
        async with httpx.AsyncClient(timeout=12) as h:
            marine = await h.get(
                "https://marine-api.open-meteo.com/v1/marine",
                params={
                    "latitude": lat, "longitude": lng,
                    "current": "wave_height,wave_period,wave_direction,swell_wave_height",
                    "hourly": "wave_height,wave_period",
                    "timezone": "auto",
                },
            )
            wind = await h.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lng,
                    "current": "wind_speed_10m,wind_gusts_10m,wind_direction_10m,temperature_2m,weather_code",
                    "timezone": "auto",
                },
            )
        marine_j = marine.json() if marine.status_code == 200 else {}
        wind_j = wind.json() if wind.status_code == 200 else {}
    except Exception as e:
        srv.logger.warning("weather fetch failed: %s", e)
        return {"alerts": [], "current": {}, "error": "weather_unavailable"}

    cur_marine = marine_j.get("current", {}) or {}
    cur_wind = wind_j.get("current", {}) or {}
    wave_h = cur_marine.get("wave_height") or 0
    wind_kmh = cur_wind.get("wind_speed_10m") or 0
    wind_kn = round(wind_kmh / 1.852, 1)
    gust_kmh = cur_wind.get("wind_gusts_10m") or 0
    gust_kn = round(gust_kmh / 1.852, 1)

    alerts = []
    if wind_kn >= 33:
        alerts.append({"severity": "danger", "title": "Coup de vent",
                       "description": f"Vent {wind_kn} kn — restez au port"})
    elif wind_kn >= 22:
        alerts.append({"severity": "warning", "title": "Vent fort",
                       "description": f"Vent {wind_kn} kn — prudence"})
    if gust_kn >= 40:
        alerts.append({"severity": "danger", "title": "Rafales violentes",
                       "description": f"Rafales {gust_kn} kn"})
    if wave_h >= 2.5:
        alerts.append({"severity": "danger", "title": "Forte houle",
                       "description": f"Vagues {wave_h} m"})
    elif wave_h >= 1.5:
        alerts.append({"severity": "warning", "title": "Mer agitée",
                       "description": f"Vagues {wave_h} m"})
    if not alerts:
        alerts.append({"severity": "info", "title": "Mer praticable",
                       "description": "Aucun avis particulier"})

    return {
        "alerts": alerts,
        "current": {
            "wind_speed_kn": wind_kn,
            "wind_gust_kn": gust_kn,
            "wind_direction": cur_wind.get("wind_direction_10m"),
            "temperature": cur_wind.get("temperature_2m"),
            "wave_height_m": wave_h,
            "wave_period_s": cur_marine.get("wave_period"),
            "swell_height_m": cur_marine.get("swell_wave_height"),
        },
    }
