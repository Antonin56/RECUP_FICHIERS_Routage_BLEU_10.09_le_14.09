"""Purge one-shot (10/07/2026) — supprime tous les comptes sauf l'admin
(pseudo SignalMar / antoninlepinay@gmail.com) + toutes les données
rattachées aux comptes supprimés. Les signalements (reports) sont
CONSERVÉS : le pseudo auteur y est dénormalisé, l'affichage carte reste
intact.
"""
import asyncio
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

ADMIN_EMAIL = "antoninlepinay@gmail.com"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "signalmar")]
    admin = await db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "user_id": 1, "pseudo": 1})
    assert admin and admin.get("pseudo") == "SignalMar", f"admin introuvable: {admin}"
    keep = admin["user_id"]
    print("Admin conservé:", keep)

    r = await db.users.delete_many({"user_id": {"$ne": keep}})
    print("users supprimés:", r.deleted_count)

    # Données rattachées aux comptes supprimés
    print("sessions:", (await db.user_sessions.delete_many({"user_id": {"$ne": keep}})).deleted_count)
    print("otp_codes:", (await db.otp_codes.delete_many({})).deleted_count)
    print("friend_requests:", (await db.friend_requests.delete_many({})).deleted_count)
    print("notifications:", (await db.notifications.delete_many({"user_id": {"$ne": keep}})).deleted_count)
    print("points_history:", (await db.points_history.delete_many({"user_id": {"$ne": keep}})).deleted_count)
    print("referrals:", (await db.referrals.delete_many({})).deleted_count)

    # Groupes : on garde uniquement ceux dont l'admin est propriétaire,
    # et on retire les membres fantômes partout.
    ghost_groups = await db.groups.find({"owner_id": {"$ne": keep}}, {"group_id": 1}).to_list(None)
    ghost_ids = [g["group_id"] for g in ghost_groups if g.get("group_id")]
    print("groups supprimés:", (await db.groups.delete_many({"owner_id": {"$ne": keep}})).deleted_count)
    if ghost_ids:
        await db.group_members.delete_many({"group_id": {"$in": ghost_ids}})
        await db.group_invitations.delete_many({"group_id": {"$in": ghost_ids}})
    print("group_members fantômes:", (await db.group_members.delete_many({"user_id": {"$ne": keep}})).deleted_count)
    print("group_invitations restantes purgées:", (await db.group_invitations.delete_many({"inviter_id": {"$ne": keep}})).deleted_count)

    # Nettoie la liste d'amis de l'admin (tous supprimés).
    await db.users.update_one({"user_id": keep}, {"$set": {"friends": []}})

    print("---- état final ----")
    for c in ["users", "groups", "group_members", "group_invitations",
              "friend_requests", "notifications", "points_history", "reports"]:
        print(c, await db[c].count_documents({}))


asyncio.run(main())
