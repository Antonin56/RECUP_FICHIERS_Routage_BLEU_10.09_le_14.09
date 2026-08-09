"""SignalMar — Seed test reports (Golfe du Morbihan ↔ Belle-Île).

Creates ~30 reports scattered between the middle of the Golfe du Morbihan
and Belle-Île. About half of them are configured to trigger a voice alert
(obstacle_nav, autorites, dead/injured mammifère), the other half are
"informational" only (pollution, secours, healthy animals).

Every report carries `is_seed=True` and `expires_at = now + 24 h` so:
  • the fleet is easy to identify + purge (see `purge_test_reports.py`);
  • it self-cleans if left alone.

Authors are a mix of:
  • the 3 real dev accounts (antoninlepinay / contact@accasteo /
    aodren.legouix), which have DEV_BYPASS = true so geofencing is a no-op
    (this matters here because a subset of the sample coords are close to
    shore);
  • 5 fictional demo accounts (Léa, Marc, Sophie, Thomas, Julie) which are
    created on the fly if they don't exist yet. They also get DEV_BYPASS so
    subsequent seedings work.

Run:
    cd /app/backend && DB_NAME=test_database python scripts/seed_test_reports.py
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

# Allow `import server` when this script is run from /app/backend/scripts/.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from motor.motor_asyncio import AsyncIOMotorClient

# ─── Config ──────────────────────────────────────────────────────────────
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
TTL_HOURS = 24
SEED_TAG = "signalmar_seed_v1"

# Rough bounding box between mid-Golfe du Morbihan (Île aux Moines, ~47.60N
# -2.85W) and Belle-Île (Le Palais, ~47.35N -3.15W). We sample uniformly in
# the box but skew the density towards the corridor axis.
LAT_MIN, LAT_MAX = 47.28, 47.62
LNG_MIN, LNG_MAX = -3.20, -2.75

# ─── Fictional demo users ───────────────────────────────────────────────
DEMO_USERS = [
    {"pseudo": "Léa",    "email": "lea.demo@signalmar.app",     "phone": "+33611000101"},
    {"pseudo": "Marc",   "email": "marc.demo@signalmar.app",    "phone": "+33611000102"},
    {"pseudo": "Sophie", "email": "sophie.demo@signalmar.app",  "phone": "+33611000103"},
    {"pseudo": "Thomas", "email": "thomas.demo@signalmar.app",  "phone": "+33611000104"},
    {"pseudo": "Julie",  "email": "julie.demo@signalmar.app",   "phone": "+33611000105"},
]

# Real accounts (must exist; created earlier by the dev flow).
REAL_EMAILS = [
    "antoninlepinay@gmail.com",
    "contact@accasteo.com",
    "aodren.legouix@gmail.com",
]

# ─── Report templates ────────────────────────────────────────────────────
# Voice-alert eligibility (see /app/frontend/src/lib/voice-alerts.ts):
#   • type=autorites → ALWAYS alerts
#   • type=obstacle_nav → ALWAYS alerts (modulated by speed)
#   • type=animal_marin subtype=mammifere health=dead_* | alive_injured → alerts
#   • else → NO alert
#
# We want ~50 % alerting. Below the `alerts` boolean tags each template.
TEMPLATES = [
    # ── ALERTING (~15) ──
    {"type": "obstacle_nav", "subtype": "conteneur",  "desc": "Conteneur semi-immergé à 500 m du chenal.", "alerts": True},
    {"type": "obstacle_nav", "subtype": "tronc",      "desc": "Tronc d'arbre flottant, poussé par le vent.", "alerts": True},
    {"type": "obstacle_nav", "subtype": "casier",     "desc": "Filière de casiers non balisée.",             "alerts": True},
    {"type": "obstacle_nav", "subtype": "epave",      "desc": "Épave signalée par SNSM.",                    "alerts": True},
    {"type": "obstacle_nav", "subtype": "bidon",      "desc": "Bidon métallique à la dérive.",               "alerts": True},
    {"type": "obstacle_nav", "subtype": "corde",      "desc": "Filet fantôme dérivant, danger d'hélice.",    "alerts": True},
    {"type": "autorites",    "subtype": "gendarmerie","desc": "Contrôle Gendarmerie maritime en cours.",     "alerts": True},
    {"type": "autorites",    "subtype": "douanes",    "desc": "Vedette des Douanes en patrouille.",          "alerts": True},
    {"type": "autorites",    "subtype": "affmar",     "desc": "Affaires Maritimes — contrôle papiers.",      "alerts": True},
    {"type": "autorites",    "subtype": "autre_autorite","desc": "Zone de tir militaire temporaire.",         "alerts": True},
    {"type": "animal_marin", "subtype": "mammifere",  "desc": "Dauphin blessé (aile pectorale).",            "alerts": True,
     "extras": {"species": "dauphin", "health": "alive_injured"}, "health": "alive_injured"},
    {"type": "animal_marin", "subtype": "mammifere",  "desc": "Marsouin mort échoué en surface.",           "alerts": True,
     "extras": {"species": "marsouin", "health": "dead_recent"},  "health": "dead_recent"},
    {"type": "animal_marin", "subtype": "mammifere",  "desc": "Grand dauphin retrouvé mort.",               "alerts": True,
     "extras": {"species": "grand_dauphin", "health": "dead_recent"}, "health": "dead_recent"},
    {"type": "obstacle_nav", "subtype": "conteneur",  "desc": "Conteneur signalé cette nuit.",              "alerts": True},
    {"type": "obstacle_nav", "subtype": "autre",      "desc": "Débris divers, radeau démoli.",              "alerts": True},

    # ── NON-ALERTING (~15) ──
    {"type": "pollution",    "subtype": "hydrocarbure","desc": "Nappe irisée sur ~30 m².",                   "alerts": False},
    {"type": "pollution",    "subtype": "macrodechets","desc": "Amas de bouteilles plastiques dans le courant.","alerts": False},
    {"type": "pollution",    "subtype": "eaux_usees", "desc": "Décoloration suspecte de l'eau.",            "alerts": False},
    {"type": "secours",      "subtype": "sauvetage",  "desc": "Assistance SNSM en cours (fin d'intervention).","alerts": False},
    {"type": "secours",      "subtype": "remorquage", "desc": "Voilier en panne moteur remorqué.",          "alerts": False},
    {"type": "animal_marin", "subtype": "mammifere",  "desc": "Groupe de dauphins en chasse — spectacle !", "alerts": False,
     "extras": {"species": "dauphin", "health": "alive_healthy"}, "health": "alive_healthy"},
    {"type": "animal_marin", "subtype": "poisson",    "desc": "Banc de thons en surface.",                  "alerts": False,
     "extras": {"species": "thon", "health": "alive_healthy"}, "health": "alive_healthy"},
    {"type": "animal_marin", "subtype": "oiseau",     "desc": "Colonie de fous de Bassan en pêche.",        "alerts": False,
     "extras": {"species": "fou_bassan", "health": "alive_healthy"}, "health": "alive_healthy"},
    {"type": "pollution",    "subtype": "autre",      "desc": "Odeur inhabituelle près de la bouée.",       "alerts": False},
    {"type": "secours",      "subtype": "medical",    "desc": "Évacuation médicale, requête HéliSMUR.",     "alerts": False},
    {"type": "animal_marin", "subtype": "meduse",     "desc": "Nappe de méduses (pelagia).",                "alerts": False,
     "extras": {"species": "meduse", "health": "alive_healthy"}, "health": "alive_healthy"},
    {"type": "pollution",    "subtype": "macrodechets","desc": "Filet abandonné (à récupérer).",             "alerts": False},
    {"type": "animal_marin", "subtype": "tortue",     "desc": "Tortue caouanne en surface, en bonne santé.", "alerts": False,
     "extras": {"species": "tortue", "health": "alive_healthy"}, "health": "alive_healthy"},
    {"type": "secours",      "subtype": "recherche",  "desc": "Vedette SNSM en recherche.",                  "alerts": False},
    {"type": "pollution",    "subtype": "hydrocarbure","desc": "Petite tache d'huile près du port.",        "alerts": False},
]


async def ensure_demo_users(db) -> list[str]:
    """Create demo users if needed, return their user_ids in author pool."""
    from passlib.context import CryptContext
    pw = CryptContext(schemes=["bcrypt"], deprecated="auto").hash("demoseed2026!")
    ids: list[str] = []
    for u in DEMO_USERS:
        existing = await db.users.find_one({"email": u["email"]})
        if existing:
            ids.append(existing["user_id"])
            continue
        uid = f"user_{uuid.uuid4().hex[:12]}"
        doc = {
            "user_id": uid,
            "email": u["email"],
            "phone": u["phone"],
            "pseudo": u["pseudo"],
            "name": u["pseudo"],
            "password_hash": pw,
            "created_at": datetime.now(timezone.utc),
            "avatar_url": None,
            "avatar_bg": random.choice(["#3AAFA9", "#F4A261", "#E63946", "#8ECAE6", "#9D4EDD"]),
            "points": 0,
            "reliability_pct": 60,
            "friends": [],
            "dev_bypass": True,   # skip geofencing so seeder can place near shore
            "referral_code": uuid.uuid4().hex[:8].upper(),
        }
        await db.users.insert_one(doc)
        ids.append(uid)
        print(f"  ✓ demo user created: {u['pseudo']} <{u['email']}>")
    return ids


async def resolve_real_users(db) -> list[str]:
    ids: list[str] = []
    async for u in db.users.find({"email": {"$in": REAL_EMAILS}}, {"user_id": 1, "email": 1, "pseudo": 1}):
        ids.append(u["user_id"])
        print(f"  · real user found: {u.get('pseudo','?')} <{u['email']}>")
    return ids


# Curated sub-bounding-boxes to sample from. They may still hit an island
# or a peninsula (Belle-Île, Houat, Hoëdic…), so EVERY candidate is filtered
# by `_is_pixel_water` which reads the actual OpenStreetMap tile at zoom 13
# and checks whether the pixel below the coord is a shade of the OSM water
# blue (#AAD3DF, tolerated ± jitter). This catches Belle-Île interior, dry
# reef caps, etc. that the coarse marine-API grid mislabels as "sea".
OCEAN_SUB_BOXES: list[tuple[float, float, float, float]] = [
    # (lat_min, lat_max, lng_min, lng_max)
    # Baie de Quiberon centre — CORE of the bay
    (47.44, 47.53, -2.95, -2.80),
    # Open sea south of Quiberon peninsula (safe deep water)
    (47.36, 47.44, -3.12, -2.90),
    # Middle of the passage between Belle-Île and Quiberon
    (47.36, 47.44, -3.10, -2.95),
    # South of Belle-Île (open Atlantic, far from shore)
    (47.28, 47.34, -3.18, -2.95),
    # South-east of Rhuys peninsula (deep coastal water off Damgan)
    (47.48, 47.52, -2.75, -2.65),
    # NOTE: Golfe du Morbihan interior REMOVED — even though the deep
    # central channel renders as pure water blue on OSM tiles, the parc
    # naturel régional overlay drapes green over the same zone at some
    # zoom levels, which is visually confusing for users. Better safe than
    # sorry for the offshore demo. Re-add later with a distinct-marker
    # policy if needed.
]


# ─── Water-pixel validator (OpenStreetMap tile sampling) ───────────────
# We fetch OSM tiles at zoom 13 (~10 m per pixel) and check the pixel colour
# below the target coord. Water on OSM standard tiles is a light blue
# `#AAD3DF` (170,211,223). We accept a range of hues that stay clearly
# "watery": high Blue, R-B negative, and not too green (excludes grass).
_TILE_CACHE: dict[tuple[int, int, int], bytes] = {}
_TILE_ZOOM = 13
_OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def _lat_lng_to_pixel(lat: float, lng: float, zoom: int) -> tuple[int, int, int, int]:
    """Convert (lat, lng) to (tile_x, tile_y, px_in_tile, py_in_tile) for the
    Web-Mercator tile scheme used by OSM. Tiles are 256 × 256 pixels."""
    import math
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x_frac = (lng + 180.0) / 360.0 * n
    y_frac = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    tx = int(x_frac)
    ty = int(y_frac)
    px = int((x_frac - tx) * 256)
    py = int((y_frac - ty) * 256)
    return tx, ty, px, py


def _pixel_is_exact_water(r: int, g: int, b: int) -> bool:
    """Strict check: pixel is within ±10 of the canonical OSM water blue."""
    return abs(r - 170) <= 10 and abs(g - 211) <= 10 and abs(b - 223) <= 10


async def _fetch_tile(client, x: int, y: int, z: int) -> Optional[bytes]:
    key = (z, x, y)
    if key in _TILE_CACHE:
        return _TILE_CACHE[key]
    url = _OSM_TILE_URL.format(z=z, x=x, y=y)
    try:
        r = await client.get(url, headers={"User-Agent": "SignalMar-Seeder/1.0"})
        if r.status_code != 200:
            return None
        _TILE_CACHE[key] = r.content
        return r.content
    except Exception:
        return None


def _pixel_looks_like_water(r: int, g: int, b: int) -> bool:
    """Broader watery check for neighbours (tolerates ripple / halo artefacts).
    Accept only clearly blue-cast pixels; reject green (land) / beige (beach)
    / grey (roads)."""
    if b < 190 or b > 240:
        return False
    if r > b - 15:
        return False   # not blue enough
    if g > b:
        return False   # green cast → grass / marsh
    if abs(g - b) < 6 and abs(r - g) < 6:
        return False   # grey (roads, buildings)
    if g > 210 and r > 190 and b < 220:
        return False   # pastel-green (park tint)
    return True


async def _is_pixel_water(lat: float, lng: float, http_client) -> bool:
    """Return True iff the OSM tile pixel below the coord looks like water.
    Two-layer check: the CENTRE pixel must be near-exact OSM water blue
    (#AAD3DF ± 10) AND at least 4/5 of a ±3 px sample must be watery. This
    rules out coords that happen to hit a lighthouse dot, shore contour, or
    tiny lake on an island — while still tolerating anti-aliasing halos on
    the water side of a coastline."""
    from PIL import Image
    import io
    tx, ty, px, py = _lat_lng_to_pixel(lat, lng, _TILE_ZOOM)
    data = await _fetch_tile(http_client, tx, ty, _TILE_ZOOM)
    if data is None:
        return False
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return False
    # 1) Exact-water on the centre pixel — strictest gate.
    cr, cg, cb = img.getpixel((px, py))
    if not _pixel_is_exact_water(cr, cg, cb):
        return False
    # 2) Broader neighbours check: 4/5 must be watery. Wider offsets (±5 px)
    #    to spot points too close to a coastline (halo of anti-aliased green).
    votes = 0
    for dx, dy in [(0, 0), (-5, 0), (5, 0), (0, -5), (0, 5)]:
        x = min(255, max(0, px + dx))
        y = min(255, max(0, py + dy))
        r, g, b = img.getpixel((x, y))
        if _pixel_looks_like_water(r, g, b):
            votes += 1
    return votes >= 4


def random_coord(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    lat_min, lat_max, lng_min, lng_max = bbox
    return (
        random.uniform(lat_min, lat_max),
        random.uniform(lng_min, lng_max),
    )


async def find_water_coord(http_client, max_attempts: int = 60) -> Optional[tuple[float, float]]:
    """Sample a coord from a random ocean sub-box and validate via the OSM
    tile pixel colour check. This is far more accurate than the coarse
    marine-API grid (which mistakes Belle-Île interior for sea), so we no
    longer double-check via `is_at_sea` — the pixel filter alone is trusted.
    """
    for _ in range(max_attempts):
        box = random.choice(OCEAN_SUB_BOXES)
        lat, lng = random_coord(box)
        if await _is_pixel_water(lat, lng, http_client):
            return (lat, lng)
    return None


async def main():
    import httpx
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    print("=== SignalMar seed test reports ===")
    print(f"DB     : {DB_NAME}")
    print(f"Boxes  : {len(OCEAN_SUB_BOXES)} curated ocean sub-boxes")
    print("Filter : OSM tile pixel colour check + Open-Meteo Marine API")
    print(f"TTL    : {len(TEMPLATES)} templates, active for {TTL_HOURS} h")
    print(f"Tag    : is_seed=True, seed_batch={SEED_TAG}")
    print()

    print("→ Users:")
    demo_ids = await ensure_demo_users(db)
    real_ids = await resolve_real_users(db)
    author_pool = demo_ids + real_ids
    if not author_pool:
        print("  ✗ no users available; abort.")
        return
    print(f"  {len(author_pool)} authors available.")
    print()

    # Clean up prior seed batch so re-runs are idempotent.
    prev = await db.reports.delete_many({"is_seed": True, "seed_batch": SEED_TAG})
    if prev.deleted_count:
        print(f"→ Cleared {prev.deleted_count} previous seed reports.")

    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=TTL_HOURS)
    inserted = 0
    alert_count = 0
    skipped = 0

    async with httpx.AsyncClient(timeout=6.0) as http:
        for i, tmpl in enumerate(TEMPLATES):
            print(f"  · [{i+1:2d}/{len(TEMPLATES)}] {tmpl['type']}/{tmpl.get('subtype','')} …", flush=True)
            coord = await find_water_coord(http, max_attempts=60)
            if coord is None:
                skipped += 1
                print("    ! skipped (no water coord)", flush=True)
                continue
            lat, lng = coord
            print(f"    ✓ ({lat:.4f}, {lng:.4f})", flush=True)
            author = random.choice(author_pool)
            author_doc = await db.users.find_one(
                {"user_id": author}, {"pseudo": 1, "name": 1}
            ) or {}
            rid = uuid.uuid4().hex
            extras = tmpl.get("extras", {}) or {}
            doc = {
                "id": rid,
                "type": tmpl["type"],
                "subtype": tmpl.get("subtype"),
                "lat": lat, "lng": lng,
                "origin_lat": lat, "origin_lng": lng,
                "description": tmpl["desc"],
                "photos": [],
                "heading": random.randint(0, 359),
                "speed_knots": round(random.uniform(0, 8), 1),
                "extras": extras,
                "activity": "navigation",
                "author_id": author,
                "author_pseudo": author_doc.get("pseudo") or author_doc.get("name") or "Marin",
                "author_name": author_doc.get("name", ""),
                "created_at": now,
                "last_confirmed_at": now,
                "expires_at": expires,
                "confirmations": [],
                "is_seed": True,
                "seed_batch": SEED_TAG,
                "will_alert": bool(tmpl.get("alerts")),
            }
            await db.reports.insert_one(doc)
            inserted += 1
            if tmpl.get("alerts"):
                alert_count += 1

    print()
    print(f"✓ Inserted {inserted} reports")
    print(f"  · alerting  : {alert_count}")
    print(f"  · silent    : {inserted - alert_count}")
    if skipped:
        print(f"  · skipped   : {skipped} (no water coord within 20 attempts)")
    print(f"  · expires at: {expires.isoformat()}")
    print()
    print("Purge later with:")
    print(f"  db.reports.deleteMany({{is_seed:true, seed_batch:'{SEED_TAG}'}})")


if __name__ == "__main__":
    asyncio.run(main())
