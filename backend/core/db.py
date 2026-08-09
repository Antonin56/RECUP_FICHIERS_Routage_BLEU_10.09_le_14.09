"""MongoDB client + database handle (P0 decouple).

Extracted from ``server.py`` so downstream modules can depend on the DB
without pulling the whole monolith into their import graph. Kept minimal
on purpose:

    from core.db import db     # global handle used everywhere
    from core.db import client # AsyncIOMotorClient (rarely needed)

``server.py`` re-exports both symbols for backward compat with existing
routers (``import server as srv; srv.db``).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# ``load_dotenv`` is idempotent — running it here as well as in ``server.py``
# guarantees the env is populated whenever this module is imported first
# (tests, migrations, ad-hoc scripts, etc.).
_ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

client: AsyncIOMotorClient = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


__all__ = ["client", "db", "MONGO_URL", "DB_NAME"]
