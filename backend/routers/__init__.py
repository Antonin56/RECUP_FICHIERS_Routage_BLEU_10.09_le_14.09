"""SignMar API routers (split from the monolithic server.py).

Each router is a self-contained FastAPI APIRouter that imports helpers,
shared state (db, app singletons) and Pydantic models directly from
``server`` (the canonical module). This keeps the refactor low-risk:
helpers stay where they are, only HTTP endpoints move out.

The refactor preserves *all* existing API paths byte-for-byte —
``/api/auth/register`` stays at the same URL — because each sub-router
declares its own ``prefix`` and the top-level ``api`` router (with prefix
``/api``) includes them.
"""
