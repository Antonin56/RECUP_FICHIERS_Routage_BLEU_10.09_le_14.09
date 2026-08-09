"""Seed varied reports for antoninlepinay@gmail.com — incl. flagged fakes."""
import asyncio
import os
import uuid
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import bcrypt

load_dotenv(Path(__file__).parent / ".env")
client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
EMAIL = "antoninlepinay@gmail.com"
PASSWORD = "SignMar2026!"

TYPES = ["authorities", "obstacle", "pollution", "fishing_act", "ofni", "fishing_pro", "species"]
DESCRIPTIONS = {
    "authorities": "Vedette de surveillance aperçue.",
    "obstacle": "Filet dérivant à la surface.",
    "pollution": "Trace d'hydrocarbures visible.",
    "fishing_act": "Chasse de fous de Bassan + dauphins.",
    "ofni": "Conteneur partiellement immergé.",
    "fishing_pro": "Chalutier en zone restreinte.",
    "species": "Groupe de grands dauphins observé.",
}

async def main():
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()
    u = await db.users.find_one({"email": EMAIL}, {"_id": 0})
    if not u:
        uid = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": uid, "email": EMAIL, "name": "Antonin Le Pinay",
            "password_hash": pw_hash,
            "provider": "email", "picture": "", "points": 120,
            "notify_radius_km": 15.0, "muted_types": [],
            "created_at": datetime.now(timezone.utc),
        })
    else:
        uid = u["user_id"]
        # Idempotent: always refresh password_hash + name so the documented
        # test credentials remain valid even if the user was previously seeded
        # with a different password or different display name.
        await db.users.update_one(
            {"user_id": uid},
            {"$set": {
                "password_hash": pw_hash,
                "name": "Antonin Le Pinay",
                "provider": "email",
            }},
        )
    name = "Antonin Le Pinay"
    await db.reports.delete_many({"author_id": uid})
    now = datetime.now(timezone.utc)
    random.seed(42)
    docs = []
    # 15 varied reports across the Morbihan / Belle-Île area.
    coords = [(47.55,-2.78),(47.60,-2.85),(47.46,-2.92),(47.40,-3.14),(47.51,-2.90),
              (47.33,-3.02),(47.58,-2.74),(47.49,-2.95),(47.42,-3.10),(47.55,-2.86),
              (47.47,-2.88),(47.61,-2.81),(47.36,-3.05),(47.50,-3.00),(47.44,-2.97)]
    for i,(lat,lng) in enumerate(coords):
        t = random.choice(TYPES)
        # 3 fakes (flagged via community)
        is_fake = i in (2, 7, 12)
        plat = lat+random.uniform(-0.01,0.01)
        plng = lng+random.uniform(-0.01,0.01)
        doc = {
            "id": uuid.uuid4().hex, "type": t, "lat": plat, "lng": plng,
            # Phase 2: origin coords frozen for the 1 km author-edit radius.
            "origin_lat": plat, "origin_lng": plng,
            "description": DESCRIPTIONS[t],
            "photos": [], "heading": None, "speed_knots": None,
            "subtype": None, "activity": None,
            "author_id": uid, "author_name": name,
            "created_at": now - timedelta(hours=random.randint(1, 36)),
            # Keep seed reports visible for ~23h so they remain testable.
            "expires_at": now + timedelta(hours=23),
            "confirmations": [],
            "edits": [],
            "status": "active",
            "flagged_fake": is_fake,
        }
        if t == "authorities":
            doc["subtype"] = random.choice(["affmar","gendmar","gendarmerie","police_env"])
            act = random.choice(["navigation","control","stationary"])
            doc["activity"] = act
            if act == "navigation":
                doc["heading"] = random.randint(0,359)
                doc["speed_knots"] = random.randint(6,18)
        doc["last_confirmed_at"] = doc["created_at"]
        docs.append(doc)
    await db.reports.insert_many(docs)
    print(f"Seeded {len(docs)} reports for {EMAIL} (uid={uid})")

if __name__ == "__main__":
    asyncio.run(main())
