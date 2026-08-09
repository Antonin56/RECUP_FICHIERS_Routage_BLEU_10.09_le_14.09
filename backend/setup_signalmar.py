"""SignalMar — Phase A bootstrap script.

Wipes all existing reports, sets up the maintainer account with the requested
pseudo / title / password, and leaves the DB in a clean state ready for the
Phase A.2 demo-reports generator (30 reports across the Morbihan / Belle-Île
area with Gemini Nano Banana photos).

Run with:  python /app/backend/setup_signalmar.py
"""

import asyncio
import os
import bcrypt
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMAIL = "antoninlepinay@gmail.com"
PSEUDO = "SignalMar"
TITLE = "Amiral Modérateur"
PASSWORD = "123454321"


async def main():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    # --- 1) Wipe all reports + report-related ephemeral collections ---------
    res = await db.reports.delete_many({})
    msgs = await db.report_messages.delete_many({})
    print(f"Wiped: {res.deleted_count} reports, {msgs.deleted_count} messages")

    # --- 2) Set up the maintainer account -----------------------------------
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()
    update = {
        "pseudo": PSEUDO,
        "title": TITLE,
        "password_hash": pw_hash,
        "provider": "email",
    }
    existing = await db.users.find_one({"email": EMAIL}, {"_id": 0})
    if existing:
        await db.users.update_one({"email": EMAIL}, {"$set": update})
        uid = existing["user_id"]
        print(f"Updated maintainer account uid={uid}")
    else:
        import uuid
        uid = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": uid,
            "email": EMAIL,
            "name": "Antonin Le Pinay",
            **update,
            "picture": "",
            "points": 0,
            "notify_radius_km": 15.0,
            "muted_types": [],
            "created_at": datetime.now(timezone.utc),
        })
        print(f"Created maintainer account uid={uid}")

    # Also wipe any deletion_log / quota counters so the dev account is clean,
    # and reset the points counter to 0 so the ranks modal demo starts on
    # "Mousse" (Phase A.2 demo-friendly default).
    await db.users.update_one(
        {"user_id": uid},
        {"$unset": {"deletions_log": ""}, "$set": {"points": 0}},
    )
    print("✅ SignalMar Phase A bootstrap complete.")
    print(f"   Login: {EMAIL} / {PASSWORD}")
    print(f"   Pseudo: {PSEUDO} — Title: {TITLE}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
