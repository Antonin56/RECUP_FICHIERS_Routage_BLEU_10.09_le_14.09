"""Seed demo SignMar reports around the Golfe du Morbihan / Belle-Île."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]


async def ensure_demo_user():
    u = await db.users.find_one({"email": "demo@signmar.app"}, {"_id": 0})
    if u:
        return u
    # We just need a synthetic author for the seeded reports.
    uid = f"user_demo_{uuid.uuid4().hex[:8]}"
    doc = {
        "user_id": uid,
        "email": "demo@signmar.app",
        "name": "Skipper Démo",
        "picture": "",
        "provider": "system",
        "points": 250,
        "created_at": datetime.now(timezone.utc),
    }
    await db.users.insert_one(doc)
    return doc


def make(uid, name, **overrides):
    now = datetime.now(timezone.utc)
    base = {
        "id": uuid.uuid4().hex,
        "lat": 47.55,
        "lng": -2.85,
        "type": "obstacle",
        "description": "",
        "photos": [],
        "heading": None,
        "speed_knots": None,
        "subtype": None,
        "activity": None,
        "author_id": uid,
        "author_name": name,
        "created_at": now,
        "last_confirmed_at": now,
        "confirmations": [],
    }
    base.update(overrides)
    base["last_confirmed_at"] = base["created_at"]
    return base


async def main():
    user = await ensure_demo_user()
    uid, name = user["user_id"], user["name"]
    now = datetime.now(timezone.utc)
    # Remove previously seeded demo reports so the script is idempotent.
    await db.reports.delete_many({"author_id": uid})

    samples = [
        make(uid, name, type="authorities", lat=47.5453, lng=-2.7846,
             subtype="gendmar", activity="navigation", heading=185, speed_knots=12,
             description="Vedette Gendarmerie Maritime — route au 185, 12 nds.",
             created_at=now - timedelta(hours=14)),
        make(uid, name, type="authorities", lat=47.4032, lng=-3.1450,
             subtype="affmar", activity="control",
             description="Contrôle des Affaires Maritimes près de Belle-Île.",
             created_at=now - timedelta(hours=20)),
        make(uid, name, type="authorities", lat=47.5170, lng=-2.9210,
             subtype="police_env", activity="stationary",
             description="Police de l'environnement, stationnaire sortie golfe.",
             created_at=now - timedelta(hours=30)),
        make(uid, name, type="ofni", lat=47.4570, lng=-2.9510,
             description="Conteneur partiellement immergé — danger collision.",
             created_at=now - timedelta(hours=16)),
        make(uid, name, type="obstacle", lat=47.5840, lng=-2.7220,
             description="Filet dérivant signalé par plusieurs voiliers.",
             created_at=now - timedelta(hours=18)),
        make(uid, name, type="pollution", lat=47.3725, lng=-3.0530,
             description="Nappe d'hydrocarbures sur ~300m.",
             created_at=now - timedelta(hours=22)),
        make(uid, name, type="fishing_act", lat=47.4960, lng=-2.9810,
             description="Chasse de fous de Bassan + dauphins.",
             created_at=now - timedelta(hours=25)),
        make(uid, name, type="species", lat=47.3290, lng=-3.0190,
             description="Famille de grands dauphins observée.",
             created_at=now - timedelta(hours=28)),
        # Some "live" (<12h) reports — only visible after login.
        make(uid, name, type="authorities", lat=47.5510, lng=-2.8650,
             subtype="gendarmerie", activity="control",
             description="Gendarmerie en contrôle à la sortie d'Arzon.",
             created_at=now - timedelta(hours=2)),
        make(uid, name, type="ofni", lat=47.4810, lng=-2.9120,
             description="Bidon plastique flottant.",
             created_at=now - timedelta(minutes=45)),
    ]
    await db.reports.insert_many(samples)
    print(f"Seeded {len(samples)} reports (uid={uid})")


if __name__ == "__main__":
    asyncio.run(main())
