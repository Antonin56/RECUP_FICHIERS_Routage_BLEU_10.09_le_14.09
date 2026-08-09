"""SignalMar — Marées Open-Meteo (20/07/2026, choix armateur : gratuit, approché).

Source : API Marine Open-Meteo (sea_level_height_msl, horaire, sans clé).
- Heures/hauteurs de BM/PM : extrema locaux de la série horaire, affinés par
  ajustement parabolique (précision ~±10 min).
- COEFFICIENT approché : marnage simultané à BREST / (2 × U=3.05 m) × 100
  (définition officielle du coefficient, calé sur l'Unité de Hauteur de
  Brest). Précision ±3 environ — NON OFFICIEL (l'API SHOM SPM est payante ;
  l'architecture permet de la brancher plus tard).
- Hauteurs affichées RELATIVES AU NIVEAU MOYEN (réf. MSL d'Open-Meteo),
  converties approximativement au-dessus du zéro hydrographique en ajoutant
  le niveau moyen local ≈ semi-marnage local moyen (affiché « ~ »).

Ports de référence : liste embarquée Bretagne Sud (zone pilote) — mêmes
ports que l'annuaire SHOM (capture armateur).
"""
from __future__ import annotations

import math
import time
from typing import Optional

import httpx

U_BREST = 3.05          # Unité de hauteur (coef 100) à Brest, en m.
BREST = (48.383, -4.495)
CACHE_TTL_S = 6 * 3600
FORECAST_DAYS = 5

# (id, nom, lat, lng)
PORTS: list[tuple[str, str, float, float]] = [
    ("port-navalo", "Port-Navalo", 47.5486, -2.9186),
    ("crouesty", "Le Crouesty", 47.5420, -2.8950),
    ("vannes", "Vannes", 47.6410, -2.7750),
    ("arradon", "Arradon", 47.6180, -2.8220),
    ("auray", "Auray (St-Goustan)", 47.6640, -2.9800),
    ("locmariaquer", "Locmariaquer", 47.5690, -2.9450),
    ("larmor-baden", "Larmor-Baden", 47.5850, -2.8950),
    ("ile-aux-moines", "Île-aux-Moines", 47.5930, -2.8510),
    ("saint-armel", "Saint-Armel (Le Passage)", 47.5850, -2.7230),
    ("le-logeo", "Le Logeo", 47.5600, -2.7850),
    ("la-trinite", "La Trinité-sur-Mer", 47.5870, -3.0280),
    ("port-haliguen", "Port Haliguen (Quiberon)", 47.4870, -3.1000),
    ("port-maria", "Port Maria (Quiberon)", 47.4780, -3.1220),
    ("portivy", "Portivy", 47.5220, -3.1400),
    ("etel", "Port d'Étel", 47.6560, -3.2090),
    ("houat", "Houat", 47.3920, -2.9550),
    ("hoedic", "Hoëdic", 47.3400, -2.8780),
    ("le-palais", "Le Palais (Belle-Île)", 47.3470, -3.1520),
    ("sauzon", "Sauzon (Belle-Île)", 47.3730, -3.2180),
    ("penerf", "Pénerf", 47.5100, -2.6530),
    ("trehiguier", "Tréhiguier", 47.5020, -2.4570),
    ("port-louis", "Port-Louis (Locmalo)", 47.7060, -3.3520),
    ("lorient", "Lorient", 47.7450, -3.3650),
    ("port-tudy", "Port-Tudy (Groix)", 47.6450, -3.4470),
    ("le-croisic", "Le Croisic", 47.2980, -2.5120),
    ("la-turballe", "La Turballe", 47.3460, -2.5080),
    # 23/07/2026 — extension de zone (façade Ouest) : ports de référence NON
    # calibrés (calage ZH générique, cf. _generic_calibration) — précision
    # moindre qu'en zone pilote, disclaimer affiché.
    ("concarneau", "Concarneau", 47.8720, -3.9180),
    ("loctudy", "Loctudy", 47.8360, -4.1720),
    ("audierne", "Audierne", 48.0230, -4.5390),
    ("douarnenez", "Douarnenez", 48.0960, -4.3290),
    ("brest", "Brest", 48.3810, -4.4950),
    ("le-conquet", "Le Conquet", 48.3600, -4.7700),
    ("ouessant", "Ouessant (Lampaul)", 48.4530, -5.0950),
    ("roscoff", "Roscoff", 48.7270, -3.9850),
    ("perros-guirec", "Perros-Guirec", 48.8140, -3.4390),
    ("paimpol", "Paimpol", 48.7770, -3.0410),
    ("saint-quay", "Saint-Quay-Portrieux", 48.6490, -2.8210),
    ("saint-malo", "Saint-Malo", 48.6430, -2.0270),
    ("saint-nazaire", "Saint-Nazaire", 47.2670, -2.2020),
    ("pornic", "Pornic", 47.1120, -2.1090),
    ("noirmoutier", "Noirmoutier (L'Herbaudière)", 47.0290, -2.2980),
    ("port-joinville", "Île d'Yeu (Port-Joinville)", 46.7300, -2.3480),
    ("saint-gilles", "Saint-Gilles-Croix-de-Vie", 46.6960, -1.9470),
    ("les-sables", "Les Sables-d'Olonne", 46.4960, -1.7950),
    ("la-rochelle", "La Rochelle", 46.1580, -1.1530),
]

_cache: dict[str, tuple[float, dict]] = {}
# 22/07/2026 — cache de la SÉRIE horaire (hauteurs / ZH) pour le moteur de
# route : clé port → (ts, times_iso_locales, hauteurs_au_dessus_du_ZH, retard_s).
_series_cache: dict[str, tuple[float, list[str], list[Optional[float]], float]] = {}

# ── 23/07/2026 — CALIBRATION PAR PORT (bug armateur « marées fausses ») ────
# Open-Meteo est un modèle OCÉANIQUE (~5 km) : il ne « voit » pas l'intérieur
# du Golfe du Morbihan (retard des PM ≈ +2 h à Vannes/Arradon, marnage réduit
# de ~20 %) et donnait les MÊMES heures/hauteurs pour tous les ports du Golfe.
# Correction affine par port, calibrée sur les prédictions officielles
# (références armateur, semaine du 22/07/2026) :
#     h_port(t) = A × h_openmeteo_msl(t − retard) + B
# B = calage sur le ZÉRO HYDRO local. Les ports du GOLFE utilisent la série
# Open-Meteo du point d'ENTRÉE (Port-Navalo), seule maille fiable.
# port_id → (retard_PM_min, retard_BM_min, A, B)
_PN = (47.5486, -2.9186)
PORT_CAL: dict[str, tuple[int, int, float, float]] = {
    # Ports CALIBRÉS sur les prédictions officielles (±15 min / ±10 cm) :
    "port-navalo": (40, 45, 1.00, 3.44),
    "arradon": (148, 138, 0.81, 1.91),
    "vannes": (150, 145, 0.77, 2.07),
    # Ports RATTACHÉS (approché — constantes du port calibré représentatif) :
    "crouesty": (40, 45, 1.00, 3.44),        # entrée du Golfe ≈ Port-Navalo
    "locmariaquer": (55, 60, 0.97, 3.30),    # ≈ Port-Navalo, léger retard
    "larmor-baden": (135, 128, 0.84, 2.05),  # ≈ Arradon, un peu plus tôt
    "ile-aux-moines": (148, 138, 0.81, 1.91),  # rattaché Arradon
    "le-logeo": (150, 140, 0.80, 1.90),      # SE du Golfe ≈ Arradon
    "saint-armel": (150, 145, 0.77, 2.07),   # fond SE ≈ Vannes
    "auray": (120, 118, 0.88, 2.40),         # rivière d'Auray (approché)
}
# Ports NON calibrés (côte ouverte) : déphasage systématique Open-Meteo
# mesuré à Port-Navalo (PM +40 min, BM +45 min) + calage ZH générique =
# extrapolation du semi-marnage au coef 120 corrigée du facteur 1,25
# (mesuré à Port-Navalo : 3,44 m réels vs 2,76 m estimés).
GENERIC_SHIFT = (40, 45)
ZH_CAL_FACTOR = 1.25


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_ports(lat: float, lng: float, n: int = 3) -> list[dict]:
    ranked = sorted(
        (
            {
                "id": pid, "name": name, "lat": plat, "lng": plng,
                "distance_km": round(_haversine_km(lat, lng, plat, plng), 1),
            }
            for pid, name, plat, plng in PORTS
        ),
        key=lambda p: p["distance_km"],
    )
    return ranked[:n]


async def _fetch_sea_level(lat: float, lng: float) -> tuple[list[str], list[Optional[float]]]:
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=sea_level_height_msl&timezone=Europe%2FParis"
        f"&forecast_days={FORECAST_DAYS}"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url)
        r.raise_for_status()
        d = r.json()
    return d["hourly"]["time"], d["hourly"]["sea_level_height_msl"]


def _extrema(times: list[str], values: list[Optional[float]]) -> list[dict]:
    """Extrema locaux (PM/BM) avec affinage parabolique sur 3 points."""
    out: list[dict] = []
    for i in range(1, len(values) - 1):
        a, b, c = values[i - 1], values[i], values[i + 1]
        if a is None or b is None or c is None:
            continue
        is_max = b >= a and b > c
        is_min = b <= a and b < c
        if not (is_max or is_min):
            continue
        # Ajustement parabolique : sommet à i + dt heures (dt ∈ [-0.5, 0.5]).
        denom = (a - 2 * b + c)
        dt = 0.0 if abs(denom) < 1e-9 else max(-1.0, min(1.0, 0.5 * (a - c) / denom))
        h = b - 0.25 * (a - c) * dt
        # times = "YYYY-MM-DDTHH:00" heure locale Europe/Paris.
        base = times[i]
        hh = int(base[11:13]) + dt
        day = base[:10]
        if hh < 0:
            hh += 24
            day = times[i - 1][:10]
        elif hh >= 24:
            hh -= 24
            day = times[i + 1][:10]
        out.append({
            "type": "PM" if is_max else "BM",
            "day": day,
            "time": f"{int(hh):02d}:{int(round((hh % 1) * 60)) % 60:02d}",
            "t_h": hh,
            "height_msl": round(float(h), 2),
        })
    return out


def _coefficient(pm_event: dict, brest_events: list[dict]) -> Optional[int]:
    """Coefficient approché : marnage Brest de la même marée / (2×U) × 100."""
    # PM de Brest la plus proche en temps (± 4 h, même jour ou adjacent).
    best, best_gap = None, 4.5
    for i, e in enumerate(brest_events):
        if e["type"] != "PM":
            continue
        gap = abs(e["t_h"] - pm_event["t_h"]) + (0 if e["day"] == pm_event["day"] else 24)
        gap = min(gap, abs(gap - 24))
        if gap < best_gap:
            best, best_gap = i, gap
    if best is None:
        return None
    h_pm = brest_events[best]["height_msl"]
    lows = [
        brest_events[j]["height_msl"]
        for j in (best - 1, best + 1)
        if 0 <= j < len(brest_events) and brest_events[j]["type"] == "BM"
    ]
    if not lows:
        return None
    marnage = h_pm - sum(lows) / len(lows)
    coef = round(marnage / (2 * U_BREST) * 100)
    return max(20, min(120, coef))


# ── 23/07/2026 — décalage d'un événement de marée (retard port) ────────────
def _shift_event(day: str, t_h: float, minutes: int) -> tuple[str, str, float]:
    """(jour, "HH:MM", t_h) après ajout du retard, avec bascule de jour."""
    from datetime import datetime, timedelta

    dt = datetime.strptime(day, "%Y-%m-%d") + timedelta(hours=t_h + minutes / 60.0)
    new_th = dt.hour + dt.minute / 60.0
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"), new_th


def _generic_zh_offset(events: list[dict], brest_events: list[dict]) -> float:
    """Calage ZH générique (ports non calibrés) : semi-marnage extrapolé au
    coef 120 × facteur de calibration mesuré à Port-Navalo."""
    offsets = []
    for i, e in enumerate(events):
        if e["type"] != "PM":
            continue
        lows = [events[j]["height_msl"] for j in (i - 1, i + 1)
                if 0 <= j < len(events) and events[j]["type"] == "BM"]
        if not lows:
            continue
        semi = (e["height_msl"] - sum(lows) / len(lows)) / 2
        coef = _coefficient(e, brest_events)
        if coef:
            offsets.append(semi * 120.0 / coef * ZH_CAL_FACTOR)
    return round(sum(offsets) / len(offsets), 2) if offsets else 0.0


async def tides_for(lat: float, lng: float) -> dict:
    ports = nearest_ports(lat, lng, n=3)
    port = ports[0]
    key = port["id"]
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_TTL_S:
        result = dict(cached[1])
        result["port"] = {**port}
        result["nearest_ports"] = ports
        return result

    times_p, vals_p = await _fetch_sea_level(*(_PN if key in PORT_CAL else (port["lat"], port["lng"])))
    times_b, vals_b = await _fetch_sea_level(*BREST)
    events = _extrema(times_p, vals_p)
    brest_events = _extrema(times_b, vals_b)

    # 23/07/2026 — correction PAR PORT (retards + affine vers le ZH local).
    cal = PORT_CAL.get(key)
    if cal:
        shift_pm, shift_bm, a_cal, b_cal = cal
        approx = key not in ("port-navalo", "arradon", "vannes")
    else:
        shift_pm, shift_bm = GENERIC_SHIFT
        a_cal, b_cal = 1.0, _generic_zh_offset(events, brest_events)
        approx = True
    mean_level = b_cal

    days: dict[str, list[dict]] = {}
    for e in events:
        # Coefficient calculé sur l'événement BRUT (avant décalage horaire).
        coef = _coefficient(e, brest_events) if e["type"] == "PM" else None
        day, hhmm, _ = _shift_event(
            e["day"], e["t_h"], shift_pm if e["type"] == "PM" else shift_bm)
        days.setdefault(day, []).append({
            "type": e["type"],
            "time": hhmm,
            "height_m": round(a_cal * e["height_msl"] + b_cal, 2),
            "coef": coef,
        })
    payload = {
        "source": ("Open-Meteo calibré sur prédictions officielles (non officiel)"
                   if not approx else "Open-Meteo corrigé (approché — non officiel)"),
        "mean_level_offset_m": mean_level,
        "days": [{"date": d, "events": evs} for d, evs in sorted(days.items())],
    }
    _cache[key] = (now, payload)
    result = dict(payload)
    result["port"] = port
    result["nearest_ports"] = ports
    return result


# ── 22/07/2026 (GO armateur) — HAUTEUR DE MARÉE POUR LE MOTEUR DE ROUTE ────
# La route automatique peut intégrer la hauteur d'eau à l'heure de départ :
# hauteur MINIMALE au-dessus du ZÉRO HYDRO sur [départ, départ + durée
# estimée] (conservateur : la marée peut descendre pendant le trajet).
async def _series_above_zh(lat: float, lng: float) -> tuple[dict, list[str], list[Optional[float]], float]:
    """(port, times locales Europe/Paris, hauteurs ≈ au-dessus du ZH, retard_s).
    23/07 : hauteurs calibrées par port (h = A × msl + B) ; le RETARD local
    (moyenne PM/BM) est retourné pour décaler les lectures temporelles."""
    port = nearest_ports(lat, lng, n=1)[0]
    key = port["id"]
    now = time.time()
    cached = _series_cache.get(key)
    if cached and now - cached[0] < CACHE_TTL_S:
        return port, cached[1], cached[2], cached[3]
    cal = PORT_CAL.get(key)
    times_p, vals_p = await _fetch_sea_level(*(_PN if cal else (port["lat"], port["lng"])))
    times_b, vals_b = await _fetch_sea_level(*BREST)
    if cal:
        shift_pm, shift_bm, a_cal, b_cal = cal
    else:
        shift_pm, shift_bm = GENERIC_SHIFT
        events = _extrema(times_p, vals_p)
        brest_events = _extrema(times_b, vals_b)
        a_cal, b_cal = 1.0, _generic_zh_offset(events, brest_events)
    shift_s = (shift_pm + shift_bm) / 2.0 * 60.0
    heights = [None if v is None else round(a_cal * v + b_cal, 2) for v in vals_p]
    _series_cache[key] = (now, times_p, heights, shift_s)
    return port, times_p, heights, shift_s


def _interp_at(times: list[str], heights: list[Optional[float]], epoch: float) -> Optional[float]:
    """Interpolation linéaire de la série horaire (times = ISO locales
    Europe/Paris) à un instant epoch UTC. None si hors série/troué."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Paris")
    dt = datetime.fromtimestamp(epoch, tz)
    key = dt.strftime("%Y-%m-%dT%H:00")
    try:
        i = times.index(key)
    except ValueError:
        return None
    frac = (dt.minute * 60 + dt.second) / 3600.0
    a = heights[i]
    b = heights[i + 1] if i + 1 < len(heights) else a
    if a is None or b is None:
        return None
    return a + (b - a) * frac


async def tide_window(lat: float, lng: float, start_epoch: float, hours: float) -> Optional[dict]:
    """Hauteur d'eau (≈ au-dessus du ZH) au départ + MINIMUM sur la fenêtre
    [départ, départ + hours]. None si données indisponibles."""
    try:
        port, times, heights, shift_s = await _series_above_zh(lat, lng)
    except Exception:
        return None
    # Le retard local s'applique en LISANT la série à (t − retard).
    h_start = _interp_at(times, heights, start_epoch - shift_s)
    if h_start is None:
        return None
    samples: list[float] = []
    n = max(2, int(hours * 4) + 1)  # tous les 1/4 h
    for k in range(n):
        h = _interp_at(times, heights, start_epoch - shift_s + k * hours * 3600.0 / (n - 1))
        if h is not None:
            samples.append(h)
    if not samples:
        return None
    return {
        "port": port["name"],
        "height_start_m": round(h_start, 2),
        "height_min_m": round(min(samples), 2),
        "window_h": round(hours, 1),
    }


async def tide_curve(
    lat: float, lng: float, start_epoch: float, hours: float = 24.0, step_s: float = 1800.0,
) -> Optional[dict]:
    """28/07 (demande armateur) — COURBE de marée pour la RouteCard : hauteurs
    ≈/ZH au port le plus proche, échantillonnées toutes les step_s sur
    [start, start+hours]. → {port, points: [{ts, h}]}. None si indisponible."""
    try:
        port, times, heights, shift = await _series_above_zh(lat, lng)
    except Exception:
        return None
    pts: list[dict] = []
    n = int(hours * 3600.0 / step_s) + 1
    for k in range(n):
        t = start_epoch + k * step_s
        h = _interp_at(times, heights, t - shift)
        if h is None:
            continue
        pts.append({"ts": int(t), "h": round(h, 2)})
    if len(pts) < 4:
        return None
    return {"port": port["name"], "points": pts}


async def tide_crossings(
    lat: float, lng: float, start_epoch: float, need_m: float, hours: float = 24.0,
) -> Optional[dict]:
    """26/07 (GO armateur) — fenêtres de marée SUFFISANTE (hauteur ≈/ZH ≥
    need_m) au port le plus proche, sur [start, start+hours]. Alimente la
    RouteCard : « passable jusqu'à ~HH:MM » / « repassera à partir de ~HH:MM ».
    Retourne aussi la PLEINE MER max de l'horizon (pour le calcul hypothétique
    « jusqu'où irait la route à pleine mer »). None si série indisponible."""
    try:
        port, times, heights, shift = await _series_above_zh(lat, lng)
    except Exception:
        return None
    if not times:
        return None
    now_h = _interp_at(times, heights, start_epoch - shift)
    if now_h is None:
        return None
    out: dict = {
        "port": port["name"],
        "now_m": round(now_h, 2),
        "now_ok": bool(now_h >= need_m),
        "next_ok_ts": None,   # 1er instant où h ≥ need (si pas déjà le cas)
        "ok_until_ts": None,  # fin de la fenêtre suffisante courante
        "max_m": round(now_h, 2),
        "max_ts": start_epoch,
    }
    step = 600.0
    t = start_epoch
    end = start_epoch + hours * 3600.0
    prev_ok = out["now_ok"]
    while t < end:
        t += step
        h = _interp_at(times, heights, t - shift)
        if h is None:
            break
        if h > out["max_m"]:
            out["max_m"], out["max_ts"] = round(h, 2), t
        ok = h >= need_m
        if out["now_ok"] and prev_ok and not ok and out["ok_until_ts"] is None:
            out["ok_until_ts"] = t
        if not out["now_ok"] and not prev_ok and ok and out["next_ok_ts"] is None:
            out["next_ok_ts"] = t
        prev_ok = ok
    return out
